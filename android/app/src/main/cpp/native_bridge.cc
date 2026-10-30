#include <jni.h>
#include <chrono>
#include <cstring>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <thread>
#include "msgq/ipc.h"
#include "msgq/event.h"
#include "msgq/visionipc/visionipc_client.h"
#include "msgq/visionipc/visionipc_server.h"

namespace {
constexpr char payload[] = "openpilot Android cross-process IPC";
constexpr VisionStreamType kProbeStream = 1;
using Clock = std::chrono::steady_clock;
void wait_for_file(const std::string &path) {
  auto deadline = Clock::now() + std::chrono::seconds(20);
  while (!std::ifstream(path).good()) {
    if (Clock::now() > deadline) throw std::runtime_error("Timed out waiting for IPC peer");
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
}
std::string ipc_probe(const std::string &root, bool publisher) {
  setenv("MSGQ_ROOT", root.c_str(), 1);
  auto context = std::unique_ptr<Context>(Context::create());
  if (publisher) {
    SocketEventHandle events("android_probe_events");
    events.set_enabled(true);
    auto pub = std::unique_ptr<PubSocket>(PubSocket::create(context.get(), "android_probe", false, 65536));
    VisionIpcServer server("android_probe");
    server.create_buffers(kProbeStream, 2, 64, 32);
    server.start_listener();
    std::ofstream(root + "/publisher.ready").put('1');
    wait_for_file(root + "/subscriber.ready");
    if (pub->send(const_cast<char *>(payload), sizeof(payload)) < 0) throw std::runtime_error("msgq send failed");
    auto buf = server.get_buffer(kProbeStream);
    std::memset(buf->addr, 37, buf->len);
    VisionIpcBufExtra extra = {};
    extra.frame_id = 17;
    server.send(buf, &extra);
    events.recv_called().wait(20);
    events.recv_called().clear();
    events.recv_ready().set();
    wait_for_file(root + "/received.ok");
  } else {
    wait_for_file(root + "/publisher.ready");
    SocketEventHandle events("android_probe_events", "", false);
    if (!events.is_enabled()) throw std::runtime_error("Replay event shared state mismatch");
    auto sub = std::unique_ptr<SubSocket>(SubSocket::create(context.get(), "android_probe", "127.0.0.1", false, false, 65536));
    sub->setTimeout(20000);
    VisionIpcClient client("android_probe", kProbeStream, false);
    auto deadline = Clock::now() + std::chrono::seconds(20);
    while (!client.connect(false)) {
      if (Clock::now() > deadline) throw std::runtime_error("VisionIPC connection failed");
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    std::ofstream(root + "/subscriber.ready").put('1');
    auto msg = std::unique_ptr<Message>(sub->receive());
    if (!msg || msg->getSize() != sizeof(payload) || std::memcmp(msg->getData(), payload, sizeof(payload)))
      throw std::runtime_error("msgq payload mismatch");
    VisionIpcBufExtra extra = {};
    auto buf = client.recv(&extra, 20000);
    if (!buf || extra.frame_id != 17) throw std::runtime_error("VisionIPC frame metadata mismatch");
    for (size_t i = 0; i < buf->len; ++i)
      if (static_cast<unsigned char *>(buf->addr)[i] != 37) throw std::runtime_error("VisionIPC buffer mismatch");
    events.recv_called().set();
    events.recv_ready().wait(20);
    std::ofstream(root + "/received.ok").put('1');
  }
  return "msgq, replay events and VisionIPC cross-process probe passed";
}
}

extern "C" JNIEXPORT jstring JNICALL
Java_ai_comma_openpilot_sim_NativeBridge_ipc(JNIEnv *env, jclass, jstring path, jboolean publisher) {
  const char *raw = env->GetStringUTFChars(path, nullptr);
  std::string root(raw);
  env->ReleaseStringUTFChars(path, raw);
  try { return env->NewStringUTF(ipc_probe(root, publisher).c_str()); }
  catch (const std::exception &failure) {
    env->ThrowNew(env->FindClass("java/lang/IllegalStateException"), failure.what());
    return nullptr;
  }
}
