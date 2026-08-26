cmake_minimum_required(VERSION 3.22)
project(ermao_archive_jni LANGUAGES C)

set(ERMAO_ARCHIVE_CORE_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../../native/archive-core")
set(ERMAO_ARCHIVE_BUILD_TESTS OFF CACHE BOOL "" FORCE)
add_subdirectory("${ERMAO_ARCHIVE_CORE_ROOT}" "${CMAKE_CURRENT_BINARY_DIR}/archive-core")

add_library(ermao_archive_jni SHARED archive_jni.c)
set_target_properties(ermao_archive_jni PROPERTIES
    C_STANDARD 11
    C_STANDARD_REQUIRED YES
    C_EXTENSIONS NO
)
target_link_libraries(ermao_archive_jni PRIVATE Ermao::ArchiveCore)
target_link_options(
    ermao_archive_jni
    PRIVATE "-Wl,--version-script=${CMAKE_CURRENT_LIST_DIR}/archive_exports.map"
)
