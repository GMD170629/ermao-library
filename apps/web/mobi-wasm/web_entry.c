#include "ermao_mobi.h"

/* Keeps the authoritative C ABI reachable when the static archive is linked by emcc. */
ERMAO_MOBI_EXPORT uint32_t ermao_mobi_web_abi_anchor(void) {
    return ermao_mobi_abi_version();
}

/*
 * Emscripten lowers a uint64_t C argument to two wasm32 parameters. Keep that
 * lowering out of the JavaScript protocol by exposing an explicit low/high
 * wrapper whose seven-argument ABI is stable and testable.
 */
ERMAO_MOBI_EXPORT ErmaoMobiStatus ermao_mobi_web_read_resource(
    const ErmaoMobiBook *book,
    uint32_t resource_index,
    uint32_t offset_low,
    uint32_t offset_high,
    uint8_t *buffer,
    uint32_t capacity,
    uint32_t *out_read
) {
    const uint64_t offset = ((uint64_t) offset_high << 32u) | (uint64_t) offset_low;
    return ermao_mobi_read_resource(book, resource_index, offset, buffer, capacity, out_read);
}
