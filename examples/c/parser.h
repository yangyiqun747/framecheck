#ifndef FRAMECHECK_PARSER_H
#define FRAMECHECK_PARSER_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#define FC_EXPORT __declspec(dllexport)
#elif defined(__GNUC__)
#define FC_EXPORT __attribute__((visibility("default")))
#else
#define FC_EXPORT
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*fc_emit_fn)(uint8_t seq, uint8_t type,
    const uint8_t *payload, size_t length, void *user);

FC_EXPORT void fc_reset(void);
FC_EXPORT int fc_feed(const uint8_t *data, size_t length, fc_emit_fn emit, void *user);

#ifdef __cplusplus
}
#endif
#endif
