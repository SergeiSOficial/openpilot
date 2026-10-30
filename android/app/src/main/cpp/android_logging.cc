#ifdef __ANDROID__
#include <android/log.h>
#else
#include <cstdio>
#endif
#include <cstdarg>
#include <cstdint>
#include "common/swaglog.h"

namespace {
void write_log(int level, const char *format, va_list arguments) {
#ifdef __ANDROID__
  int priority = level >= CLOUDLOG_ERROR ? ANDROID_LOG_ERROR : level >= CLOUDLOG_WARNING ? ANDROID_LOG_WARN :
                 level >= CLOUDLOG_INFO ? ANDROID_LOG_INFO : ANDROID_LOG_DEBUG;
  __android_log_vprint(priority, "openpilot.native", format, arguments);
#else
  (void)level;
  std::vfprintf(stderr, format, arguments);
  std::fputc('\n', stderr);
#endif
}
}

void cloudlog_e(int level, const char *, int, const char *, const char *format, ...) {
  va_list args;
  va_start(args, format);
  write_log(level, format, args);
  va_end(args);
}
void cloudlog_te(int level, const char *, int, const char *, const char *format, ...) {
  va_list args;
  va_start(args, format);
  write_log(level, format, args);
  va_end(args);
}
void cloudlog_te(int level, const char *, int, const char *, uint32_t, const char *format, ...) {
  va_list args;
  va_start(args, format);
  write_log(level, format, args);
  va_end(args);
}
