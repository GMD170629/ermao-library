cmake_minimum_required(VERSION 3.22)
project(ermao_mobi_jni LANGUAGES C)

set(ERMAO_MOBI_CORE_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../../native/mobi-core")
set(ERMAO_MOBI_BUILD_TESTS OFF CACHE BOOL "" FORCE)
add_subdirectory("${ERMAO_MOBI_CORE_ROOT}" "${CMAKE_CURRENT_BINARY_DIR}/mobi-core")

add_library(ermao_mobi_jni SHARED mobi_jni.c)
set_target_properties(ermao_mobi_jni PROPERTIES
    C_STANDARD 99
    C_STANDARD_REQUIRED YES
    C_EXTENSIONS NO
)
target_link_libraries(ermao_mobi_jni PRIVATE Ermao::MobiCore)
target_link_options(
    ermao_mobi_jni
    PRIVATE "-Wl,--version-script=${CMAKE_CURRENT_LIST_DIR}/mobi_exports.map"
)
