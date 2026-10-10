/* FrameCheck teaching parser. FC_BUG=0 is the correct implementation.
 * FC_BUG=1: loses partial frames between calls.
 * FC_BUG=2: emits at most one message per call, dropping the remainder.
 * FC_BUG=3: accepts corrupt CRCs.
 * FC_BUG=4: fails to recover after leading noise.
 */
#include "parser.h"
#include <string.h>

#ifndef FC_BUG
#define FC_BUG 0
#endif

#define FC_MAX_PAYLOAD 64u
#define FC_MAX_FRAME (FC_MAX_PAYLOAD + 7u)

static uint8_t buffer[FC_MAX_FRAME];
static size_t used;
#if FC_BUG == 4
static int desynced;
#endif

static uint16_t crc16(const uint8_t *bytes, size_t length)
{
    uint16_t crc = 0xffffu;
    size_t i;
    unsigned bit;
    for (i = 0; i < length; ++i) {
        crc ^= (uint16_t)((uint16_t)bytes[i] << 8);
        for (bit = 0; bit < 8u; ++bit) {
            crc = (uint16_t)((crc & 0x8000u) ?
                ((uint32_t)crc << 1) ^ 0x1021u : (uint32_t)crc << 1);
        }
    }
    return crc;
}

static void drop(size_t count)
{
    used -= count;
    memmove(buffer, buffer + count, used);
}

FC_EXPORT void fc_reset(void)
{
    used = 0;
#if FC_BUG == 4
    desynced = 0;
#endif
}

/* Consume every complete candidate, retaining a partial suffix. */
static int drain(fc_emit_fn emit, void *user)
{
    int emitted = 0;
    while (used != 0u) {
        size_t payload_length;
        size_t total;
        uint16_t expected;
        uint16_t actual;
        if (buffer[0] != 0xaau || (used >= 2u && buffer[1] != 0x55u)) {
#if FC_BUG == 4
            desynced = 1;
            used = 0;
            return emitted;
#else
            drop(1u);
            continue;
#endif
        }
        if (used < 3u) {
            return emitted;
        }
        payload_length = buffer[2];
        if (payload_length > FC_MAX_PAYLOAD) {
            drop(1u);
            continue;
        }
        total = payload_length + 7u;
        if (used < total) {
            return emitted;
        }
        expected = (uint16_t)((uint16_t)buffer[total - 2u] |
            ((uint16_t)buffer[total - 1u] << 8));
        actual = crc16(buffer + 2u, payload_length + 3u);
#if FC_BUG != 3
        if (expected != actual) {
            /* The failed candidate can contain the beginning of a valid one. */
            drop(1u);
            continue;
        }
#else
        (void)expected;
        (void)actual;
#endif
        if (emit != NULL) {
            emit(buffer[3], buffer[4], buffer + 5u, payload_length, user);
        }
        ++emitted;
        drop(total);
    }
    return emitted;
}

FC_EXPORT int fc_feed(const uint8_t *data, size_t length, fc_emit_fn emit, void *user)
{
    size_t i;
    int emitted = 0;
    if (data == NULL && length != 0u) {
        return -1;
    }
#if FC_BUG == 1
    used = 0;
#endif
#if FC_BUG == 4
    if (desynced) {
        return 0;
    }
#endif
    for (i = 0; i < length; ++i) {
        /* drain always frees a full buffer, even for an invalid candidate. */
        if (used == sizeof(buffer)) {
            drop(1u);
        }
        buffer[used++] = data[i];
        emitted += drain(emit, user);
#if FC_BUG == 2
        if (emitted != 0) {
            used = 0;
            break;
        }
#endif
#if FC_BUG == 4
        if (desynced) {
            break;
        }
#endif
    }
#if FC_BUG == 1
    used = 0;
#endif
    return emitted;
}
