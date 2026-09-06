cmake_minimum_required(VERSION 3.22)
project(ermao_chapter_jni LANGUAGES C)

option(ERMAO_CHAPTER_BUILD_HOST "Build the JNI bridge for the host JVM test process" OFF)
set(ERMAO_CHAPTER_HOST_OUTPUT_DIR "" CACHE PATH "Output directory for the host JNI library")
set(ERMAO_CHAPTER_JNI_INCLUDE_DIR "" CACHE PATH "JDK JNI include directory for host builds")
set(ERMAO_CHAPTER_JNI_PLATFORM_INCLUDE_DIR "" CACHE PATH "Platform-specific JDK JNI include directory for host builds")

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

if(ERMAO_CHAPTER_BUILD_HOST)
    if(NOT ERMAO_CHAPTER_HOST_OUTPUT_DIR)
        message(FATAL_ERROR "ERMAO_CHAPTER_HOST_OUTPUT_DIR is required for host JNI builds")
    endif()
    if(NOT ERMAO_CHAPTER_JNI_INCLUDE_DIR OR NOT ERMAO_CHAPTER_JNI_PLATFORM_INCLUDE_DIR)
        message(FATAL_ERROR "JDK JNI include directories are required for host JNI builds")
    endif()

    target_include_directories(ermao_chapter_jni PRIVATE
        "${ERMAO_CHAPTER_JNI_INCLUDE_DIR}"
        "${ERMAO_CHAPTER_JNI_PLATFORM_INCLUDE_DIR}"
    )

    set_target_properties(ermao_chapter_jni PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${ERMAO_CHAPTER_HOST_OUTPUT_DIR}"
        LIBRARY_OUTPUT_DIRECTORY "${ERMAO_CHAPTER_HOST_OUTPUT_DIR}"
        ARCHIVE_OUTPUT_DIRECTORY "${ERMAO_CHAPTER_HOST_OUTPUT_DIR}"
    )
    if(WIN32)
        set_target_properties(ermao_chapter_jni PROPERTIES PREFIX "")
    endif()
endif()

target_link_libraries(ermao_chapter_jni PRIVATE ermao_chapters)
if(NOT ERMAO_CHAPTER_BUILD_HOST OR NOT WIN32)
    target_link_options(
        ermao_chapter_jni
        PRIVATE "-Wl,--version-script=${CMAKE_CURRENT_LIST_DIR}/chapter_exports.map"
    )
endif()
