cmake_minimum_required(VERSION 3.22)
project(ermao_chapter_jni LANGUAGES C)

set(ERMAO_CHAPTER_CORE_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../../../../packages/reader-core/native/chapters")
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
add_subdirectory("${ERMAO_CHAPTER_CORE_ROOT}" "${CMAKE_CURRENT_BINARY_DIR}/chapter-core")

add_library(ermao_chapter_jni SHARED chapter_jni.c)
set_target_properties(ermao_chapter_jni PROPERTIES
    C_STANDARD 99
    C_STANDARD_REQUIRED YES
    C_EXTENSIONS NO
)
target_include_directories(ermao_chapter_jni PRIVATE "${ERMAO_CHAPTER_CORE_ROOT}/include")
target_link_libraries(ermao_chapter_jni PRIVATE ermao_chapters)
target_link_options(
    ermao_chapter_jni
    PRIVATE "-Wl,--version-script=${CMAKE_CURRENT_LIST_DIR}/chapter_exports.map"
)
