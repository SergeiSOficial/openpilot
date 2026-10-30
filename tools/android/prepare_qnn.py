"""Download released Android runtimes and create a tiny quantized test as data.

Only standard-library network, hashes, ZIP inspection and protobuf encoding run
on the host. QNN/ORT native code and model execution run exclusively on Android.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import urllib.error
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/"tools/android/.cache/qnn-deps"
ASSETS=ROOT/"tools/android/.cache/qnn-assets/acceleration"
CENTRAL="https://repo.maven.apache.org/maven2/"
PACKAGES=[("com/microsoft/onnxruntime","onnxruntime-android","1.29.0"),
          ("com/qualcomm/qti","onnxruntime-android-qnn","2.7.0"),
          ("com/qualcomm/qti","qnn-runtime","2.51.0")]


def varint(value):
    result=bytearray()
    while value>127:result.append((value&127)|128);value>>=7
    result.append(value);return bytes(result)


def integer(field,value):return varint(field<<3)+varint(value)
def binary(field,value):
    if isinstance(value,str):value=value.encode()
    return varint((field<<3)|2)+varint(len(value))+value


def tensor(name,dtype,shape,data):
    return b''.join(integer(1,value) for value in shape)+integer(2,dtype)+binary(8,name)+binary(9,data)


def value(name,dtype,shape):
    dims=b''.join(binary(1,integer(1,size)) for size in shape)
    return binary(1,name)+binary(2,binary(1,integer(1,dtype)+binary(2,dims)))


def node(name,op,inputs,outputs):
    return b''.join(binary(1,x) for x in inputs)+b''.join(binary(2,x) for x in outputs)+binary(3,name)+binary(4,op)


def model():
    initializers=[tensor("xs",1,[],struct.pack('<f',.5)),tensor("xz",2,[],bytes([128])),
                  tensor("W",3,[1,1,3,3],bytes([1])*9),tensor("ws",1,[],struct.pack('<f',.25)),tensor("wz",3,[],bytes([0])),
                  tensor("ys",1,[],struct.pack('<f',.125)),tensor("yz",2,[],bytes([128]))]
    nodes=[node("input_dequantize","DequantizeLinear",["X","xs","xz"],["xf"]),
           node("weight_dequantize","DequantizeLinear",["W","ws","wz"],["wf"]),
           node("convolution","Conv",["xf","wf"],["yf"]),
           node("output_quantize","QuantizeLinear",["yf","ys","yz"],["Y"])]
    graph=b''.join(binary(1,x) for x in nodes)+binary(2,"openpilot_qnn_symmetric_conv")
    graph+=b''.join(binary(5,x) for x in initializers)
    graph+=binary(11,value("X",2,[1,1,5,5]))+binary(12,value("Y",2,[1,1,3,3]))
    return integer(1,8)+binary(2,"openpilot_android_probe")+binary(7,graph)+binary(8,integer(2,13))


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--download",action="store_true");args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);ASSETS.mkdir(parents=True,exist_ok=True)
    artifacts={}
    for group,name,version in PACKAGES:
        filename=f'{name}-{version}.aar';path=OUT/filename
        url=f'{CENTRAL}{group}/{name}/{version}/{filename}'
        if not path.exists():
            if not args.download:raise RuntimeError('Run prepare_qnn.py --download first')
            partial=path.with_suffix('.aar.part')
            with urllib.request.urlopen(url,timeout=120) as response,partial.open('wb') as output:shutil.copyfileobj(response,output)
            partial.replace(path)
        checksum_url=url+'.sha1'
        with urllib.request.urlopen(checksum_url,timeout=30) as response:expected=response.read().decode().strip().split()[0]
        with path.open('rb') as stream:actual_sha1=hashlib.file_digest(stream,'sha1').hexdigest()
        if actual_sha1!=expected:raise RuntimeError('Published artifact checksum differs: '+filename)
        with zipfile.ZipFile(path) as archive:
            names=archive.namelist()
            if name=='qnn-runtime':
                required={f'jni/arm64-v8a/{library}.so' for library in
                          ('libQnnHtp','libQnnHtpPrepare','libQnnSystem','libQnnHtpV68Stub','libQnnHtpV68Skel')}
                if missing:=required-set(names):raise RuntimeError('Runtime cannot stage V68: '+str(sorted(missing)))
            libraries=[entry for entry in names if entry.startswith('jni/arm64-v8a/') and entry.endswith('.so')]
        with path.open('rb') as stream:sha256=hashlib.file_digest(stream,'sha256').hexdigest()
        artifacts[filename]={'url':url,'sha256':sha256,'published_sha1':expected,'bytes':path.stat().st_size,'arm64_libraries':libraries}
        print(f'Verified Android artifact {filename}: {path.stat().st_size} bytes',flush=True)
    data=model();(ASSETS/'qnn_probe.onnx').write_bytes(data)
    manifest={'schema':1,'runtimes':artifacts,'sha256':{'qnn_probe.onnx':hashlib.sha256(data).hexdigest()},
              'oracle':{'input':'X:uint8[1,1,5,5]','output':'Y:uint8[1,1,3,3]',
                        'uniform_128_output':[128]*9,'uniform_129_output':[137]*9,'uniform_127_output':[119]*9},
              'scope':'tiny symmetric quantized Conv hardware probe, not driving model certification'}
    (ASSETS/'qnn-probe.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Prepared quantized model as protobuf data; no host native/model execution')


if __name__=='__main__':main()
