"""Read existing unpacked Cap'n Proto timing records using only the standard library.

No capnp/numpy imports, native loading, compiler, subprocess or device execution.
Wire offsets are checked against the existing generated schema header as text.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import struct

ROOT = Path(__file__).resolve().parents[2]


class Message:
  def __init__(self, segments):
    self.segments = segments

  def word(self, segment, offset):
    data = self.segments[segment]
    if offset < 0 or (offset+1)*8 > len(data):
      raise ValueError("Cap'n Proto pointer is outside its segment")
    return struct.unpack_from('<Q', data, offset*8)[0]

  def pointer(self, segment, offset, depth=0):
    if depth > 8:
      raise ValueError("Excessive far-pointer depth")
    value = self.word(segment, offset)
    if value & 3 == 2:
      landing_segment, landing_word = value >> 32, (value >> 3) & 0x1fffffff
      if value & 4:
        far = self.word(landing_segment, landing_word)
        tag = self.word(landing_segment, landing_word+1)
        if far & 7 != 2:
          raise ValueError("Invalid double-far landing pad")
        return tag, far >> 32, (far >> 3) & 0x1fffffff
      return self.pointer(landing_segment, landing_word, depth+1)
    relative = (value >> 2) & 0x3fffffff
    if relative & 0x20000000:
      relative -= 0x40000000
    return value, segment, offset+1+relative

  def structure(self, segment, offset):
    value, segment, start = self.pointer(segment, offset)
    if value & 3:
      raise ValueError("Expected a struct pointer")
    words, pointers = (value >> 32) & 0xffff, value >> 48
    if start < 0 or (start+words+pointers)*8 > len(self.segments[segment]):
      raise ValueError("Struct is outside its segment")
    return Struct(self, segment, start, words, pointers)


class Struct:
  def __init__(self, message, segment, start, words, pointers):
    self.message, self.segment, self.start = message, segment, start
    self.words, self.pointers = words, pointers

  def scalar(self, fmt, byte_offset):
    if byte_offset+struct.calcsize(fmt) > self.words*8:
      return 0
    return struct.unpack_from('<'+fmt, self.message.segments[self.segment], self.start*8+byte_offset)[0]

  def nested(self, index):
    if index >= self.pointers:
      raise ValueError("Missing struct pointer field")
    return self.message.structure(self.segment, self.start+self.words+index)

  def text(self, index):
    if index >= self.pointers:
      return ''
    value, segment, start = self.message.pointer(self.segment, self.start+self.words+index)
    if value == 0:
      return ''
    if value & 3 != 1 or (value >> 32) & 7 != 2:
      raise ValueError("Expected a byte-list text pointer")
    count = value >> 35
    data = self.message.segments[segment][start*8:start*8+count].tobytes()
    if len(data) != count or not data.endswith(b'\0'):
      raise ValueError("Invalid text bounds or terminator")
    return data[:-1].decode('utf-8')


def messages(path):
  data = memoryview(path.read_bytes())
  cursor = 0
  while cursor < len(data):
    count = struct.unpack_from('<I', data, cursor)[0]+1
    if not 1 <= count <= 1024:
      raise ValueError("Invalid Cap'n Proto segment count")
    sizes = struct.unpack_from('<'+'I'*count, data, cursor+4)
    cursor += ((count+2)//2)*8
    segments = []
    for size in sizes:
      stop = cursor+size*8
      if stop > len(data):
        raise ValueError("Truncated Cap'n Proto message")
      segments.append(data[cursor:stop])
      cursor = stop
    yield Message(segments).structure(0, 0)


def schema_layout():
  path = ROOT/'tools/android/.cache/native-deps/cereal/gen/cpp/log.capnp.h'
  header = path.read_text()
  enum = re.search(r'struct Event \{.*?enum Which: uint16_t \{(.*?)\};', header, re.S).group(1)
  variants = re.findall(r'^\s*([A-Z][A-Z_0-9]*),', enum, re.M)
  checks = {'Event::Reader::which': 4, 'Event::Reader::getLogMonoTime': 0,
            'ModelDataV2::Reader::getModelExecutionTime': 3, 'ModelDataV2::Reader::getBig': 257,
            'ModelDataV2::Reader::getFrameId': 0, 'ModelDataV2::Reader::getTimestampEof': 2,
            'InitData::Reader::getDeviceType': 0, 'InitData::Reader::getVersion': 3,
            'InitData::Reader::getGitCommit': 8, 'InitData::Reader::getGitBranch': 9,
            'InitData::Reader::getGitSrcCommit': 19}
  for name, expected in checks.items():
    match = re.search(re.escape(name)+r'\(\) const \{(.*?)\n\}', header, re.S)
    if match is None or f'bounded<{expected}>()' not in match.group(1):
      raise ValueError(f'Schema offset changed: {name}')
  return variants, hashlib.sha256(path.read_bytes()).hexdigest()


def summary(values):
  if not values or any(not math.isfinite(x) for x in values):
    raise ValueError('Missing or non-finite timing samples')
  return {'count':len(values), 'mean':statistics.mean(values), 'median':statistics.median(values),
          'p95':statistics.quantiles(values, n=100, method='inclusive')[94], 'min':min(values), 'max':max(values)}


def timing(path, variants):
  rows, initialization = [], None
  for event in messages(path):
    kind = variants[event.scalar('H', 8)]
    if kind == 'INIT_DATA':
      info = event.nested(0)
      initialization = {'device_type':info.scalar('H',0), 'version':info.text(3), 'git_commit':info.text(8),
                        'git_branch':info.text(9), 'git_source_commit':info.text(19)}
    elif kind == 'MODEL_V2':
      model = event.nested(0)
      duration = model.scalar('f',12)*1000
      if not 0 < duration < 120000:
        raise ValueError(f'Invalid modelExecutionTime: {duration}')
      rows.append({'frame_id':model.scalar('I',0), 'model_ms':duration,
                   'big':bool(model.scalar('B',32) & 2), 'timestamp_eof':model.scalar('Q',16),
                   'log_mono_time':event.scalar('Q',0)})
  if len(rows) != 60:
    raise ValueError(f'Expected 60 model frames in {path}, got {len(rows)}')
  intervals = [(b['timestamp_eof']-a['timestamp_eof'])/1e6 for a,b in zip(rows, rows[1:])]
  return {'path':path.relative_to(ROOT).as_posix(), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
          'initialization':initialization, 'big_frames':sum(row['big'] for row in rows),
          'model_ms':summary([row['model_ms'] for row in rows]),
          'model_ms_after_first':summary([row['model_ms'] for row in rows[1:]]),
          'recorded_camera_interval_ms':summary(intervals), 'model_time_total_seconds':sum(row['model_ms'] for row in rows)/1000,
          'frames_over_50ms':sum(row['model_ms'] > 50 for row in rows), 'samples':rows}


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--session', default='d8ffcf8fb9a24397')
  parser.add_argument('--additional-session')
  args = parser.parse_args()
  if not re.fullmatch(r'[a-f0-9]{16}', args.session):
    raise ValueError('Invalid Fold 3 evidence session')
  variants, header_hash = schema_layout()
  fixture = timing(ROOT/'tools/android/.cache/fixture/fixture.rlog', variants)
  phone = timing(ROOT/f'artifacts/android/fold3/{args.session}/outputs.rlog', variants)
  verification = json.loads((ROOT/f'artifacts/android/fold3/{args.session}/verification.json').read_text())
  if not verification['verification_passed']:
    raise ValueError('Phone replay did not pass numerical acceptance')
  wall = verification['elapsed_seconds']
  report = {'schema':1, 'method':'Python standard-library-only decoding of existing recorded/model timing fields',
            'comparison_limits':['Recorded comma four uses openpilot 0.10.2 nightly-dev; the port is 0.11.2 with a separately identified model.',
                                 'Camera timestamps in Android replay are recorded virtual time, not achieved wall-clock cadence.',
                                 'Replay elapsed time includes daemon startup and numerical verification; it is not steady-state FPS.',
                                 'No physical comma four/chestnut same-model benchmark or sustained thermal test was performed.'],
            'schema_header_sha256':header_hash, 'source_sha256':verification['comparison']['source_sha256'],
            'source_revision':verification['comparison']['source_revision'], 'recorded_comma':fixture, 'fold3':phone,
            'model_mean_latency_ratio':phone['model_ms']['mean']/fixture['model_ms']['mean'],
            'fold3_all_in_fps':60/wall, 'fold3_all_in_seconds':wall,
            'fold3_all_in_seconds_per_frame':wall/60, 'fold3_all_in_slowdown_vs_20hz':wall/3,
            'fold3_model_time_fraction_of_run':phone['model_time_total_seconds']/wall,
            'fold3_model_mean_slowdown_vs_50ms':phone['model_ms']['mean']/50}
  if args.additional_session:
    if not re.fullmatch(r'[a-f0-9]{16}', args.additional_session):
      raise ValueError('Invalid additional Fold 3 evidence session')
    extra_root = ROOT/f'artifacts/android/fold3/{args.additional_session}'
    extra_verification = json.loads((extra_root/'verification.json').read_text())
    if not extra_verification['verification_passed'] or extra_verification['comparison']['source_sha256'] != report['source_sha256']:
      raise ValueError('Additional replay must pass with the same computational source')
    extra = timing(extra_root/'outputs.rlog', variants)
    report['additional_fold3'] = extra | {'all_in_seconds':extra_verification['elapsed_seconds'],
        'all_in_fps':60/extra_verification['elapsed_seconds']}
  output = ROOT/'artifacts/android/fold3/performance.json'
  output.write_text(json.dumps(report, indent=2)+'\n')
  print(json.dumps({key:value for key,value in report.items() if key not in ('recorded_comma','fold3','additional_fold3')}, indent=2))
  print('recorded comma:', json.dumps({key:value for key,value in fixture.items() if key not in ('samples','path','sha256')}))
  print('fold3:', json.dumps({key:value for key,value in phone.items() if key not in ('samples','path','sha256')}))
  if args.additional_session:
    print('additional fold3:', json.dumps({key:value for key,value in extra.items() if key not in ('samples','path','sha256')}))


if __name__ == '__main__':
  main()
