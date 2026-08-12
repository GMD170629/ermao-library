#include "ermao_mobi.h"

#include <cstdint>

int main() {
    ErmaoMobiOpenOptions options{};
    ermao_mobi_default_options(&options);
    return ermao_mobi_abi_version() == 1u
            && options.struct_size == sizeof(ErmaoMobiOpenOptions)
        ? 0
        : 1;
}
