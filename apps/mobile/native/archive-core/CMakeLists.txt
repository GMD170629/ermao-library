cmake_minimum_required(VERSION 3.22)
project(ermao_archive_core VERSION 1.0.0 LANGUAGES C)

option(ERMAO_ARCHIVE_BUILD_TESTS "Build host archive corpus tests" ON)

# Keep the vendored parser surface deliberately small. Reader archives are data
# containers, never shell inputs, and only ZIP/RAR/RAR5 are registered at run time.
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(ENABLE_TEST OFF CACHE BOOL "" FORCE)
set(ENABLE_TAR OFF CACHE BOOL "" FORCE)
set(ENABLE_CPIO OFF CACHE BOOL "" FORCE)
set(ENABLE_CAT OFF CACHE BOOL "" FORCE)
set(ENABLE_UNZIP OFF CACHE BOOL "" FORCE)
set(ENABLE_OPENSSL OFF CACHE BOOL "" FORCE)
set(ENABLE_MBEDTLS OFF CACHE BOOL "" FORCE)
set(ENABLE_NETTLE OFF CACHE BOOL "" FORCE)
set(ENABLE_LIBB2 OFF CACHE BOOL "" FORCE)
set(ENABLE_LZ4 OFF CACHE BOOL "" FORCE)
set(ENABLE_LZO OFF CACHE BOOL "" FORCE)
set(ENABLE_ZSTD OFF CACHE BOOL "" FORCE)
set(ENABLE_BZip2 OFF CACHE BOOL "" FORCE)
set(ENABLE_LIBXML2 OFF CACHE BOOL "" FORCE)
set(ENABLE_EXPAT OFF CACHE BOOL "" FORCE)
set(ENABLE_PCREPOSIX OFF CACHE BOOL "" FORCE)
set(ENABLE_ACL OFF CACHE BOOL "" FORCE)
set(ENABLE_XATTR OFF CACHE BOOL "" FORCE)
set(ENABLE_ICONV OFF CACHE BOOL "" FORCE)

add_subdirectory(vendor/libarchive-3.8.9 libarchive EXCLUDE_FROM_ALL)

# libarchive enables `-Werror` for its Android build. With every digest backend
# intentionally disabled, 3.8.9 leaves one write-only mtree local unused. This
# target-scoped suppression applies only to unmodified upstream sources; Reader
# code remains warning-clean and the write API is never registered at runtime.
if(ANDROID)
    target_compile_options(archive_static PRIVATE -Wno-unused-variable)
endif()
# Apple Clang 21 reports one pointer-sign warning in libarchive's unmodified
# write-disk implementation. The Reader never registers a write API; keep the
# suppression scoped to the upstream target so our archive-core stays clean.
if(CMAKE_C_COMPILER_ID MATCHES "Clang")
    target_compile_options(archive_static PRIVATE -Wno-pointer-sign)
endif()

add_library(ermao_archive_core STATIC src/archive_core.c)
add_library(Ermao::ArchiveCore ALIAS ermao_archive_core)
set_target_properties(ermao_archive_core PROPERTIES
    C_STANDARD 11
    C_STANDARD_REQUIRED YES
    C_EXTENSIONS NO
    POSITION_INDEPENDENT_CODE YES
    C_VISIBILITY_PRESET hidden
)
target_include_directories(ermao_archive_core PUBLIC include)
target_link_libraries(ermao_archive_core PUBLIC archive_static)

if(ERMAO_ARCHIVE_BUILD_TESTS AND NOT ANDROID)
    enable_testing()
    add_executable(ermao_archive_host_tests tests/host_tests.c)
    target_link_libraries(ermao_archive_host_tests PRIVATE Ermao::ArchiveCore)
    add_test(
        NAME ermao_archive_host_tests
        COMMAND ermao_archive_host_tests
            "${CMAKE_CURRENT_SOURCE_DIR}/../../../../test-data/library/comics/reader-pages.zip"
            "${CMAKE_CURRENT_SOURCE_DIR}/../../../../test-data/library/comics/reader-pages.cbr"
            "${CMAKE_CURRENT_SOURCE_DIR}/../../../../test-data/library/comics/reader-pages.rar"
            "${CMAKE_CURRENT_SOURCE_DIR}/../../../../test-data/library/comics/reader-pages.cbz"
    )
endif()
