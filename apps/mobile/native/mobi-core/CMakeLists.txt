cmake_minimum_required(VERSION 3.22)
project(ermao_mobi_core VERSION 1.0.0 LANGUAGES C CXX)

option(ERMAO_MOBI_BUILD_TESTS "Build host ABI and corpus tests" ON)
option(ERMAO_MOBI_ENABLE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
option(ERMAO_MOBI_BUILD_FUZZER "Build the Clang libFuzzer parsing entry point" OFF)

find_package(ZLIB REQUIRED)

set(ERMAO_MOBI_VENDOR_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/Sources/CLibMobi")
set(ERMAO_MOBI_SOURCES
    "${ERMAO_MOBI_VENDOR_ROOT}/src/buffer.c"
    "${ERMAO_MOBI_VENDOR_ROOT}/src/compression.c"
    "${ERMAO_MOBI_VENDOR_ROOT}/src/debug.c"
    "${ERMAO_MOBI_VENDOR_ROOT}/src/index.c"
    "${ERMAO_MOBI_VENDOR_ROOT}/src/memory.c"
    "${ERMAO_MOBI_VENDOR_ROOT}/src/meta.c"
    "${ERMAO_MOBI_VENDOR_ROOT}/src/opf.c"
    "${ERMAO_MOBI_VENDOR_ROOT}/src/parse_rawml.c"
    "${ERMAO_MOBI_VENDOR_ROOT}/src/read.c"
    "${ERMAO_MOBI_VENDOR_ROOT}/src/structure.c"
    "${ERMAO_MOBI_VENDOR_ROOT}/src/util.c"
    "${ERMAO_MOBI_VENDOR_ROOT}/src/write.c"
    "${ERMAO_MOBI_VENDOR_ROOT}/src/xmlwriter.c"
    "${ERMAO_MOBI_VENDOR_ROOT}/src/ermao_mobi.c"
)

add_library(ermao_mobi_core STATIC ${ERMAO_MOBI_SOURCES})
add_library(Ermao::MobiCore ALIAS ermao_mobi_core)
add_library(ermao_mobi_core_shared SHARED ${ERMAO_MOBI_SOURCES})
set_target_properties(ermao_mobi_core_shared PROPERTIES OUTPUT_NAME ermao_mobi_core)
set_target_properties(ermao_mobi_core PROPERTIES
    C_STANDARD 99
    C_STANDARD_REQUIRED YES
    C_EXTENSIONS NO
    POSITION_INDEPENDENT_CODE YES
    C_VISIBILITY_PRESET hidden
)
set_target_properties(ermao_mobi_core_shared PROPERTIES
    C_STANDARD 99
    C_STANDARD_REQUIRED YES
    C_EXTENSIONS NO
    POSITION_INDEPENDENT_CODE YES
    C_VISIBILITY_PRESET hidden
)
target_include_directories(ermao_mobi_core
    PUBLIC "${ERMAO_MOBI_VENDOR_ROOT}/public"
    PRIVATE "${ERMAO_MOBI_VENDOR_ROOT}/include" "${ERMAO_MOBI_VENDOR_ROOT}/src"
)
target_include_directories(ermao_mobi_core_shared
    PUBLIC "${ERMAO_MOBI_VENDOR_ROOT}/public"
    PRIVATE "${ERMAO_MOBI_VENDOR_ROOT}/include" "${ERMAO_MOBI_VENDOR_ROOT}/src"
)
target_compile_definitions(ermao_mobi_core PRIVATE
    PACKAGE_VERSION="0.12"
    USE_XMLWRITER
    USE_ZLIB
    HAVE_STRDUP
    HAVE_UNISTD_H
    MOBI_INLINE=inline
)
target_compile_definitions(ermao_mobi_core_shared PRIVATE
    PACKAGE_VERSION="0.12"
    USE_XMLWRITER
    USE_ZLIB
    HAVE_STRDUP
    HAVE_UNISTD_H
    MOBI_INLINE=inline
)
target_link_libraries(ermao_mobi_core PUBLIC ZLIB::ZLIB)
target_link_libraries(ermao_mobi_core_shared PUBLIC ZLIB::ZLIB)

if(ERMAO_MOBI_ENABLE_SANITIZERS AND CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
    target_compile_options(ermao_mobi_core PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(ermao_mobi_core PUBLIC -fsanitize=address,undefined)
    target_compile_options(ermao_mobi_core_shared PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(ermao_mobi_core_shared PUBLIC -fsanitize=address,undefined)
endif()

if(ERMAO_MOBI_BUILD_FUZZER AND NOT ANDROID AND CMAKE_C_COMPILER_ID MATCHES "Clang")
    target_compile_options(ermao_mobi_core PRIVATE -fsanitize=fuzzer-no-link)
    add_executable(ermao_mobi_fuzz_open tests/fuzz_open.c)
    target_link_libraries(ermao_mobi_fuzz_open PRIVATE Ermao::MobiCore)
    target_compile_options(
        ermao_mobi_fuzz_open PRIVATE -fsanitize=fuzzer,address,undefined -fno-omit-frame-pointer
    )
    target_link_options(ermao_mobi_fuzz_open PRIVATE -fsanitize=fuzzer,address,undefined)
endif()

if(ERMAO_MOBI_BUILD_TESTS AND NOT ANDROID)
    enable_testing()
    add_executable(ermao_mobi_host_tests tests/host_tests.c)
    target_link_libraries(ermao_mobi_host_tests PRIVATE Ermao::MobiCore)
    if(ERMAO_MOBI_ENABLE_SANITIZERS AND CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
        target_compile_options(ermao_mobi_host_tests PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(ermao_mobi_host_tests PRIVATE -fsanitize=address,undefined)
    endif()
    add_test(
        NAME ermao_mobi_host_tests
        COMMAND ermao_mobi_host_tests "${CMAKE_CURRENT_SOURCE_DIR}/../../../../test-data/library/mobi"
    )

    add_executable(ermao_mobi_cpp_header_test tests/cpp_header_test.cpp)
    target_link_libraries(ermao_mobi_cpp_header_test PRIVATE Ermao::MobiCore)
    add_test(NAME ermao_mobi_cpp_header_test COMMAND ermao_mobi_cpp_header_test)

    add_executable(ermao_mobi_snapshot tests/snapshot.c)
    target_link_libraries(ermao_mobi_snapshot PRIVATE Ermao::MobiCore)

    add_executable(ermao_mobi_memory_probe tests/memory_probe.c)
    target_include_directories(
        ermao_mobi_memory_probe PRIVATE "${ERMAO_MOBI_VENDOR_ROOT}/include"
    )
    target_link_libraries(ermao_mobi_memory_probe PRIVATE Ermao::MobiCore)
endif()
