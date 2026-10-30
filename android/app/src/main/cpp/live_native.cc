// Android-target capture/IPC bridge. Never built as a host test executable.
#include <jni.h>
#include <android/hardware_buffer_jni.h>
#include <android/bitmap.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <dlfcn.h>
#include <time.h>
#include <algorithm>
#include <array>
#include <cstring>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <vector>
#if defined(__aarch64__)
#include <arm_neon.h>
#endif
#include "msgq/visionipc/visionipc_server.h"
#include "msgq/visionipc/visionipc_client.h"

namespace {
uint64_t nanos(clockid_t clock) { timespec t{}; clock_gettime(clock, &t); return uint64_t(t.tv_sec)*1000000000ULL+t.tv_nsec; }
size_t align_to(size_t n, size_t a) { return (n+a-1)/a*a; }
struct Layout {
  size_t stride, yheight, uvheight, offset, size;
  Layout(int w, int h) {
    stride=align_to(w,128); yheight=align_to(h,32); uvheight=align_to(h/2,16); offset=stride*yheight;
    size=align_to(offset+stride*uvheight+4096+std::max(size_t(16384),8*stride),4096);
    size=align_to(size+align_to(w,512)*512,4096);
  }
};
struct Plane { const uint8_t *data; size_t capacity; int row, pixel; };
void pack(uint8_t *out, const Layout &l, int w, int h, const std::array<Plane,3> &p, int left, int top) {
  if (w<=0 || h<=0 || (w|h|left|top)&1 || left<0 || top<0) throw std::runtime_error("YUV crop must be positive, even and aligned");
  for (int n=0;n<3;n++) {
    int div=n?2:1, pw=w/div, ph=h/div, x=left/div, y=top/div;
    if (!p[n].data || p[n].row<=0 || p[n].pixel<=0) throw std::runtime_error("Invalid camera plane");
    size_t last=size_t(y+ph-1)*p[n].row+size_t(x+pw-1)*p[n].pixel;
    if (last>=p[n].capacity) throw std::runtime_error("Camera plane bounds mismatch");
  }
  // Active pixels are overwritten below. Clear only padding/trailer, preserving
  // the byte-exact NV12 contract without writing the full active image twice.
  std::memset(out+size_t(h)*l.stride,0,l.offset-size_t(h)*l.stride);
  std::memset(out+l.offset+size_t(h/2)*l.stride,0,l.size-l.offset-size_t(h/2)*l.stride);
  for (int y=0;y<h;y++) {
    const uint8_t *src=p[0].data+size_t(top+y)*p[0].row+size_t(left)*p[0].pixel;
    uint8_t *dst=out+size_t(y)*l.stride;
    if (p[0].pixel==1) std::memcpy(dst,src,w);
    else for (int x=0;x<w;x++) dst[x]=src[size_t(x)*p[0].pixel];
    std::memset(dst+w,0,l.stride-w);
  }
  for (int y=0;y<h/2;y++) {
    uint8_t *dst=out+l.offset+size_t(y)*l.stride;
    const uint8_t *u=p[1].data+size_t(top/2+y)*p[1].row+size_t(left/2)*p[1].pixel;
    const uint8_t *v=p[2].data+size_t(top/2+y)*p[2].row+size_t(left/2)*p[2].pixel;
    int x=0;
    if(p[1].pixel==2 && p[2].pixel==2 && u+1==v){std::memcpy(dst,u,w);x=w/2;}
#if defined(__aarch64__)
    if(p[1].pixel==1 && p[2].pixel==1)for(;x+16<=w/2;x+=16){
      uint8x16x2_t uv{{vld1q_u8(u+x),vld1q_u8(v+x)}};vst2q_u8(dst+x*2,uv);
    }
#endif
    for (;x<w/2;x++) { dst[x*2]=u[size_t(x)*p[1].pixel]; dst[x*2+1]=v[size_t(x)*p[2].pixel]; }
    std::memset(dst+w,0,l.stride-w);
  }
}
struct Capture {
  std::unique_ptr<VisionIpcServer> server;
  std::array<int,3> widths{}, heights{};
  std::array<uint32_t,3> ids{};
  std::array<uint64_t,3> counts{}, first{}, last{}, pack_ns{}, gap_max_ns{}, gap_over_100ms{}, lock_ns{};
  std::array<double,3> luma{};
  std::array<VisionBuf*,3> last_buffer{};
};
std::mutex capture_lock;
std::unique_ptr<Capture> capture;
std::array<std::unique_ptr<VisionIpcClient>,3> clients;
std::array<std::vector<uint8_t>,3> snapshots;
std::string error;
std::vector<uint8_t> driver_luma;
void configure_root(const std::string &root) {
  if (root.empty() || root.front()!='/') throw std::runtime_error("Absolute session root required");
  setenv("MSGQ_ROOT",(root+"/shm").c_str(),1); unsetenv("OPENPILOT_PREFIX");
  unsetenv("CEREAL_FAKE"); unsetenv("CEREAL_FAKE_PREFIX");
}
std::string java_string(JNIEnv *env,jstring value) {
  const char *raw=env->GetStringUTFChars(value,nullptr); std::string out(raw); env->ReleaseStringUTFChars(value,raw); return out;
}
void fail(JNIEnv *env,const std::exception &e) { env->ThrowNew(env->FindClass("java/lang/IllegalStateException"),e.what()); }
}

extern "C" JNIEXPORT void JNICALL Java_ai_comma_openpilot_sim_NativeBridge_captureStart(JNIEnv *env,jclass,jstring root,jboolean cabin_only) {
  try {
    std::lock_guard<std::mutex> lock(capture_lock);
    configure_root(java_string(env,root)); capture=std::make_unique<Capture>();
    capture->server=std::make_unique<VisionIpcServer>("camerad");
    for (int n=0;n<3;n++) {
      if (cabin_only && n!=1) continue;
      int w=n==1?1280:1920, h=n==1?720:1080; Layout l(w,h);
      capture->widths[n]=w; capture->heights[n]=h;
      capture->server->create_buffers_with_sizes(n,8,w,h,l.size,l.stride,l.offset);
    }
    capture->server->start_listener();
  } catch (const std::exception &e) { fail(env,e); }
}

extern "C" JNIEXPORT jlong JNICALL Java_ai_comma_openpilot_sim_NativeBridge_captureFrame(JNIEnv *env,jclass,jint stream,
    jobject y,jint yr,jint yp,jobject u,jint ur,jint up,jobject v,jint vr,jint vp,jint width,jint height,jint left,jint top,jlong timestamp,jboolean realtime) {
  try {
    const uint64_t lock_begin=nanos(CLOCK_MONOTONIC);
    std::lock_guard<std::mutex> lock(capture_lock);
    if (!capture || stream<0 || stream>2 || capture->widths[stream]!=width || capture->heights[stream]!=height)
      throw std::runtime_error("Capture stream dimensions mismatch");
    capture->lock_ns[stream]+=nanos(CLOCK_MONOTONIC)-lock_begin;
    std::array<Plane,3> p={{{static_cast<const uint8_t*>(env->GetDirectBufferAddress(y)),size_t(env->GetDirectBufferCapacity(y)),yr,yp},
      {static_cast<const uint8_t*>(env->GetDirectBufferAddress(u)),size_t(env->GetDirectBufferCapacity(u)),ur,up},
      {static_cast<const uint8_t*>(env->GetDirectBufferAddress(v)),size_t(env->GetDirectBufferCapacity(v)),vr,vp}}};
    uint64_t begin=nanos(CLOCK_MONOTONIC); Layout layout(width,height);
    auto *buf=capture->server->get_buffer(stream);
    // Invalidate an old ring slot before writing pixels so consumers reject a
    // snapshot overlapping the overwrite, even before the new frame is sent.
    buf->set_frame_id(0);std::atomic_thread_fence(std::memory_order_seq_cst);
    pack(static_cast<uint8_t*>(buf->addr),layout,width,height,p,left,top);
    uint64_t sensor=timestamp;
    if (realtime) sensor=uint64_t(int64_t(timestamp)+int64_t(nanos(CLOCK_MONOTONIC))-int64_t(nanos(CLOCK_BOOTTIME)));
    if(!sensor || sensor<=capture->last[stream] || (realtime && sensor>nanos(CLOCK_MONOTONIC)))
      throw std::runtime_error("Invalid camera timestamp rejected before publication");
    VisionIpcBufExtra extra{}; extra.frame_id=++capture->ids[stream]; extra.timestamp_sof=sensor;
    // No measured readout-end timestamp is available: retain capture time rather than invent exposure metadata.
    extra.timestamp_eof=sensor; extra.valid=realtime;
    std::atomic_thread_fence(std::memory_order_release);
    buf->set_frame_id(extra.frame_id); capture->server->send(buf,&extra,false);
    if(!capture->first[stream])capture->first[stream]=sensor;
    if(capture->last[stream]&&sensor>capture->last[stream]) {
      uint64_t gap=sensor-capture->last[stream];
      capture->gap_max_ns[stream]=std::max(capture->gap_max_ns[stream],gap);
      if(gap>100000000)capture->gap_over_100ms[stream]++;
    }
    double brightness=0;size_t samples=0;const auto *bytes=static_cast<const uint8_t*>(buf->addr);
    for(int row=0;row<height;row+=32)for(int col=0;col<width;col+=32){brightness+=bytes[row*layout.stride+col];samples++;}
    capture->luma[stream]=brightness/samples;
    capture->counts[stream]++; capture->last[stream]=sensor; capture->pack_ns[stream]+=nanos(CLOCK_MONOTONIC)-begin;
    capture->last_buffer[stream]=buf;
    return sensor;
  } catch (const std::exception &e) { fail(env,e); return 0; }
}

extern "C" JNIEXPORT jstring JNICALL Java_ai_comma_openpilot_sim_NativeBridge_captureStats(JNIEnv *env,jclass) {
  std::lock_guard<std::mutex> lock(capture_lock); std::ostringstream out; out<<"{\"streams\":[";
  for(int n=0;n<3;n++) {
    if(n)out<<','; uint64_t count=capture?capture->counts[n]:0;
    out<<"{\"stream\":"<<n<<",\"frames\":"<<count<<",\"timestamp_ns\":"<<(capture?capture->last[n]:0)
       <<",\"pack_mean_ms\":"<<(count?double(capture->pack_ns[n])/count/1e6:0)
       <<",\"lock_wait_mean_ms\":"<<(count?double(capture->lock_ns[n])/count/1e6:0)
       <<",\"sensor_fps\":"<<(count>1&&capture->last[n]>capture->first[n]?double(count-1)*1e9/(capture->last[n]-capture->first[n]):0)
       <<",\"gap_max_ms\":"<<(capture?double(capture->gap_max_ns[n])/1e6:0)
       <<",\"gaps_over_100ms\":"<<(capture?capture->gap_over_100ms[n]:0)
       <<",\"luma_mean\":"<<(capture?capture->luma[n]:0)
       <<",\"age_ms\":"<<(count?double(nanos(CLOCK_MONOTONIC)-capture->last[n])/1e6:0)
       <<",\"pool_slots\":8,\"capture_queue_limit\":4,\"discard_policy\":\"acquire_latest\"}";
  }
  out<<"]}";return env->NewStringUTF(out.str().c_str());
}
extern "C" JNIEXPORT void JNICALL Java_ai_comma_openpilot_sim_NativeBridge_captureStop(JNIEnv*,jclass) {
  std::lock_guard<std::mutex> lock(capture_lock);capture.reset();
}
extern "C" JNIEXPORT void JNICALL Java_ai_comma_openpilot_sim_NativeBridge_captureResetCounters(JNIEnv*,jclass) {
  std::lock_guard<std::mutex> lock(capture_lock);
  if(capture){capture->counts.fill(0);capture->first.fill(0);capture->last.fill(0);capture->pack_ns.fill(0);capture->lock_ns.fill(0);capture->gap_max_ns.fill(0);capture->gap_over_100ms.fill(0);}
}
extern "C" JNIEXPORT jboolean JNICALL Java_ai_comma_openpilot_sim_NativeBridge_captureThumbnail(JNIEnv *env,jclass,jint stream,jobject bitmap) {
  std::lock_guard<std::mutex> lock(capture_lock);
  if(!capture||stream<0||stream>2||!capture->last_buffer[stream])return false;
  AndroidBitmapInfo info{};void *pixels=nullptr;
  if(AndroidBitmap_getInfo(env,bitmap,&info)!=0||info.format!=ANDROID_BITMAP_FORMAT_RGBA_8888||AndroidBitmap_lockPixels(env,bitmap,&pixels)!=0)return false;
  auto *buf=capture->last_buffer[stream];const auto *src=static_cast<const uint8_t*>(buf->addr);
  for(size_t y=0;y<info.height;y++)for(size_t x=0;x<info.width;x++) {
    int yy=y*buf->height/info.height,xx=x*buf->width/info.width;
    int Y=src[yy*buf->stride+xx],U=src[buf->uv_offset+(yy/2)*buf->stride+(xx/2)*2]-128,V=src[buf->uv_offset+(yy/2)*buf->stride+(xx/2)*2+1]-128;
    auto *p=static_cast<uint8_t*>(pixels)+y*info.stride+x*4;
    p[0]=std::clamp(int(Y+1.402*V),0,255);p[1]=std::clamp(int(Y-0.344136*U-0.714136*V),0,255);p[2]=std::clamp(int(Y+1.772*U),0,255);p[3]=255;
  }
  AndroidBitmap_unlockPixels(env,bitmap);return true;
}

extern "C" JNIEXPORT jstring JNICALL Java_ai_comma_openpilot_sim_NativeBridge_hardwareBufferProbe(JNIEnv *env,jclass,jobject buffer) {
  if(!buffer)return env->NewStringUTF("{\"available\":false,\"reason\":\"no hardware buffer\"}");
  AHardwareBuffer *ahb=AHardwareBuffer_fromHardwareBuffer(env,buffer); AHardwareBuffer_Desc desc{}; AHardwareBuffer_describe(ahb,&desc);
  EGLDisplay display=eglGetDisplay(EGL_DEFAULT_DISPLAY); bool imported=false;
  if(eglInitialize(display,nullptr,nullptr)) {
    auto get_client=reinterpret_cast<PFNEGLGETNATIVECLIENTBUFFERANDROIDPROC>(eglGetProcAddress("eglGetNativeClientBufferANDROID"));
    auto create=reinterpret_cast<PFNEGLCREATEIMAGEKHRPROC>(eglGetProcAddress("eglCreateImageKHR"));
    auto destroy=reinterpret_cast<PFNEGLDESTROYIMAGEKHRPROC>(eglGetProcAddress("eglDestroyImageKHR"));
    if(get_client&&create&&destroy) { EGLint attrs[]={EGL_IMAGE_PRESERVED_KHR,EGL_TRUE,EGL_NONE};
      EGLImageKHR image=create(display,EGL_NO_CONTEXT,EGL_NATIVE_BUFFER_ANDROID,get_client(ahb),attrs);
      imported=image!=EGL_NO_IMAGE_KHR;if(imported)destroy(display,image);
    }
    // Display is shared with UI; never eglTerminate it from a capture callback.
  }
  std::ostringstream out;out<<"{\"available\":true,\"egl_import\":"<<(imported?"true":"false")<<",\"width\":"<<desc.width
    <<",\"height\":"<<desc.height<<",\"format\":"<<desc.format<<",\"enabled_for_inference\":false}";
  return env->NewStringUTF(out.str().c_str());
}

extern "C" const char *op_live_error() { return error.c_str(); }
extern "C" int op_live_connect(const char *root) {
  try { configure_root(root);for(int n=0;n<3;n++)clients[n]=std::make_unique<VisionIpcClient>("camerad",n,true);return 0; }
  catch(const std::exception &e){error=e.what();return -1;}
}
extern "C" const void *op_live_read(int stream,uint64_t *meta,int timeout_ms) {
  try {
    if(stream<0||stream>2||!clients[stream])return nullptr;
    auto &client=clients[stream]; if(!client->is_connected()&&!client->connect(false))return nullptr;
    VisionIpcBufExtra extra{}; auto *buf=client->recv(&extra,timeout_ms);if(!buf)return nullptr;
    if(buf->get_frame_id()!=extra.frame_id)return nullptr;
    std::atomic_thread_fence(std::memory_order_acquire);
    auto &out=snapshots[stream];out.resize(buf->len);std::memcpy(out.data(),buf->addr,buf->len);
    std::atomic_thread_fence(std::memory_order_acquire);
    if(buf->get_frame_id()!=extra.frame_id)return nullptr;
    meta[0]=extra.frame_id;meta[1]=extra.timestamp_sof;meta[2]=extra.timestamp_eof;meta[3]=buf->len;
    meta[4]=buf->width;meta[5]=buf->height;meta[6]=buf->stride;meta[7]=buf->uv_offset;meta[8]=extra.valid;
    return out.data();
  }catch(const std::exception &e){error=e.what();return nullptr;}
}
extern "C" int op_live_cl_upload(void *queue,void *memory,const void *source,size_t bytes) {
  // Blocking transfer pins the native snapshot until the GPU has consumed it.
  static void *library=dlopen("libOpenCL.so",RTLD_NOW|RTLD_LOCAL);
  using Upload=int(*)(void*,void*,unsigned int,size_t,size_t,const void*,unsigned int,const void*,void*);
  static auto upload=library?reinterpret_cast<Upload>(dlsym(library,"clEnqueueWriteBuffer")):nullptr;
  if(!upload){error="OpenCL native upload unavailable";return -1;}
  return upload(queue,memory,1,0,bytes,source,0,nullptr,nullptr);
}

extern "C" JNIEXPORT jobject JNICALL Java_ai_comma_openpilot_sim_NativeBridge_copyGpuLuma(JNIEnv *env,jclass,jlong queue,jlong memory,jint bytes) {
  try {
    if(bytes!=1440*960)throw std::runtime_error("Unexpected driver luma size");
    static void *library=dlopen("libOpenCL.so",RTLD_NOW|RTLD_LOCAL);
    using Read=int(*)(void*,void*,unsigned int,size_t,size_t,void*,unsigned int,const void*,void*);
    static auto read=library?reinterpret_cast<Read>(dlsym(library,"clEnqueueReadBuffer")):nullptr;
    if(!read)throw std::runtime_error("Native OpenCL readback unavailable");
    driver_luma.resize(bytes);
    int result=read(reinterpret_cast<void*>(queue),reinterpret_cast<void*>(memory),1,0,bytes,driver_luma.data(),0,nullptr,nullptr);
    if(result)throw std::runtime_error("Driver luma readback failed: "+std::to_string(result));
    // Single GPU coordinator owns this direct buffer until the synchronous ORT run returns.
    return env->NewDirectByteBuffer(driver_luma.data(),bytes);
  }catch(const std::exception &e){fail(env,e);return nullptr;}
}

extern "C" JNIEXPORT jstring JNICALL Java_ai_comma_openpilot_sim_NativeBridge_captureSelfTest(JNIEnv *env,jclass) {
  try {
    const int w=8,h=4;Layout l(w,h);std::vector<uint8_t> y(12*8,99),u(12*4,88),v(12*4,77),out(l.size);
    for(int r=0;r<8;r++)for(int c=0;c<12;c++)y[r*12+c]=r*12+c;
    for(int r=0;r<4;r++)for(int c=0;c<6;c++){u[r*12+c*2]=10+r*6+c;v[r*12+c*2]=40+r*6+c;}
    std::array<Plane,3> planes={{{y.data(),y.size(),12,1},{u.data(),u.size(),12,2},{v.data(),v.size(),12,2}}};
    pack(out.data(),l,w,h,planes,2,2);
    for(int r=0;r<h;r++)for(int c=0;c<w;c++)if(out[r*l.stride+c]!=(r+2)*12+c+2)throw std::runtime_error("Y plane failed");
    for(int r=0;r<h/2;r++)for(int c=0;c<w/2;c++)if(out[l.offset+r*l.stride+c*2]!=10+(r+1)*6+c+1||out[l.offset+r*l.stride+c*2+1]!=40+(r+1)*6+c+1)throw std::runtime_error("UV plane failed");
    bool rejected=false;planes[1].capacity=1;try{pack(out.data(),l,w,h,planes,2,2);}catch(const std::exception&){rejected=true;}
    if(!rejected)throw std::runtime_error("Plane bounds not rejected");
    for(int kind=0;kind<3;kind++){
      const int ww=96,hh=8,row=112;Layout layout(ww,hh);
      std::vector<uint8_t> yy(row*hh),uu(row*hh),vv(row*hh),pixels(layout.size,0xA5),expected(layout.size,0);
      for(size_t i=0;i<yy.size();i++){yy[i]=uint8_t(i*7);uu[i]=uint8_t(i*3);vv[i]=uint8_t(i*11);}
      int pixel=kind?2:1;
      std::array<Plane,3> pp={{{yy.data(),yy.size(),row,1},{uu.data(),uu.size(),row,pixel},
        {kind==2?uu.data()+1:vv.data(),kind==2?uu.size()-1:vv.size(),row,pixel}}};
      for(int y=0;y<hh;y++)for(int x=0;x<ww;x++)expected[y*layout.stride+x]=yy[y*row+x];
      for(int y=0;y<hh/2;y++)for(int x=0;x<ww/2;x++){
        expected[layout.offset+y*layout.stride+x*2]=pp[1].data[y*row+x*pixel];
        expected[layout.offset+y*layout.stride+x*2+1]=pp[2].data[y*row+x*pixel];
      }
      pack(pixels.data(),layout,ww,hh,pp,0,0);
      if(pixels!=expected)throw std::runtime_error("Optimized packing or padding differs from scalar oracle");
    }
    return env->NewStringUTF("{\"passed\":true,\"checks\":[\"padded_y\",\"pixel_stride_2_uv\",\"crop\",\"plane_bounds\",\"neon_planar_oracle\",\"aliased_nv12_oracle\",\"full_padding_oracle\"]}");
  }catch(const std::exception &e){fail(env,e);return nullptr;}
}

extern "C" JNIEXPORT jstring JNICALL Java_ai_comma_openpilot_sim_NativeBridge_capturePoolTest(JNIEnv *env,jclass,jstring root) {
  try {
    configure_root(java_string(env,root));Layout layout(8,4);
    VisionIpcServer server("live_pool_test");
    server.create_buffers_with_sizes(1,8,8,4,layout.size,layout.stride,layout.offset);server.start_listener();
    VisionIpcClient client("live_pool_test",1,true);
    bool connected=false;
    for(int attempt=0;attempt<50&&!connected;attempt++) {
      connected=client.connect(false);if(!connected)std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    if(!connected)throw std::runtime_error("Pool test client did not connect");
    // Hold a private snapshot while overwriting the same eight producer slots.
    std::vector<uint8_t> owned(layout.size,0);VisionIpcBufExtra extra{};
    for(uint32_t id=1;id<=64;id++) {
      auto *buf=server.get_buffer(1);buf->set_frame_id(0);
      std::memset(buf->addr,id,layout.size);buf->set_frame_id(id);
      extra.frame_id=id;extra.timestamp_sof=id*50000000ULL;extra.timestamp_eof=extra.timestamp_sof;extra.valid=true;
      server.send(buf,&extra,false);
      if(id==1)std::memcpy(owned.data(),buf->addr,layout.size);
    }
    auto *latest=client.recv(&extra,1000);
    if(!latest||extra.frame_id!=64||latest->get_frame_id()!=64||static_cast<uint8_t*>(latest->addr)[0]!=64)
      throw std::runtime_error("Bounded overload did not deliver the latest complete frame");
    if(owned.front()!=1||owned[layout.offset]!=1)throw std::runtime_error("Owned snapshot was overwritten");
    return env->NewStringUTF("{\"passed\":true,\"produced\":64,\"pool_slots\":8,\"latest_frame\":64,\"owned_snapshot_preserved\":true}");
  }catch(const std::exception &e){fail(env,e);return nullptr;}
}
