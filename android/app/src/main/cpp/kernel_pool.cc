// Used only by the Android kernel library. Reduction order is unchanged.
#include <atomic>
#include <condition_variable>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <mutex>
#include <thread>
#include <vector>
#include <pthread.h>
#include <sched.h>

namespace {
std::atomic<uint64_t> launches{0}, fallbacks{0};
std::atomic<int> pin_workers{0};
std::atomic<uint64_t> affinity_masks[3]{};
class Pool {
  std::mutex dispatch, mutex;
  std::condition_variable wake, done;
  std::vector<std::thread> threads;
  std::atomic<uint64_t> generation{0};
  bool stopping=false;
  std::atomic<int> pending{0};
  int total=0,lanes=4;
  void (*callback)(void*,int,int)=nullptr;
  void* context=nullptr;
  void worker(int index) {
    if (pin_workers.load(std::memory_order_relaxed)) {
      cpu_set_t mask; CPU_ZERO(&mask); CPU_SET(4+index,&mask);
      sched_setaffinity(0,sizeof(mask),&mask);
    }
    cpu_set_t actual; CPU_ZERO(&actual);
    if (sched_getaffinity(0,sizeof(actual),&actual)==0) {
      uint64_t bits=0;for(int i=0;i<64;i++)if(CPU_ISSET(i,&actual))bits|=uint64_t(1)<<i;
      affinity_masks[index-1].store(bits,std::memory_order_relaxed);
    }
    uint64_t seen=0;
    for (;;) {
      // Keep short gaps between model kernels off the futex path. Park after
      // one millisecond so inactive model services do not spin indefinitely.
      const auto deadline=std::chrono::steady_clock::now()+std::chrono::microseconds(1000);
      while(generation.load(std::memory_order_acquire)==seen && std::chrono::steady_clock::now()<deadline)
        std::atomic_signal_fence(std::memory_order_seq_cst);
      std::unique_lock lock(mutex);
      wake.wait(lock,[&]{return stopping || generation.load(std::memory_order_acquire)!=seen;});
      if (stopping) return;
      seen=generation.load(std::memory_order_relaxed);
      auto function=callback; auto argument=context; int count=total;
      lock.unlock();
      function(argument,count*index/lanes,count*(index+1)/lanes);
      lock.lock();
      if (pending.fetch_sub(1,std::memory_order_release)==1) done.notify_one();
    }
  }
public:
  Pool() {
    lanes=pin_workers.load(std::memory_order_relaxed)?3:4;
    for(int i=1;i<lanes;i++)threads.emplace_back([this,i]{worker(i);});
  }
  ~Pool() {
    { std::lock_guard lock(mutex); stopping=true; }
    wake.notify_all();
    for(auto& thread:threads)thread.join();
  }
  void run(void (*function)(void*,int,int),void* argument,int count) {
    std::lock_guard exclusive(dispatch);
    {
      std::lock_guard lock(mutex);
      callback=function; context=argument; total=count; pending.store(lanes-1,std::memory_order_relaxed);
      generation.fetch_add(1,std::memory_order_release);
    }
    wake.notify_all();
    function(argument,0,count/lanes);
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::microseconds(2000);
    while(pending.load(std::memory_order_acquire)!=0 && std::chrono::steady_clock::now()<deadline)
      std::atomic_signal_fence(std::memory_order_seq_cst);
    std::unique_lock lock(mutex);
    done.wait(lock,[&]{return pending.load(std::memory_order_acquire)==0;});
  }
};
}
extern "C" void op_parallel_launch(void (*function)(void*,int,int),void* context,int count) {
  static Pool pool;
  launches.fetch_add(1,std::memory_order_relaxed);
  pool.run(function,context,count);
}
extern "C" void op_parallel_fallback() { fallbacks.fetch_add(1,std::memory_order_relaxed); }
extern "C" void op_parallel_set_core_policy(int enabled) { pin_workers.store(enabled!=0,std::memory_order_relaxed); }
extern "C" void op_parallel_affinities(uint64_t* result) {
  for(int i=0;i<3;i++)result[i]=affinity_masks[i].load(std::memory_order_relaxed);
}
extern "C" void op_parallel_stats(uint64_t* result) {
  result[0]=launches.load(std::memory_order_relaxed);
  result[1]=fallbacks.load(std::memory_order_relaxed);
}
