cmake_minimum_required(VERSION 3.22)

project(ermao_chapters LANGUAGES C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

set(ERMAO_CHAPTERS_WARNING_OPTIONS)
if(MSVC)
    list(APPEND ERMAO_CHAPTERS_WARNING_OPTIONS /W4)
else()
    list(APPEND ERMAO_CHAPTERS_WARNING_OPTIONS -Wall -Wextra -Wpedantic -Werror)
endif()

add_library(ermao_chapters STATIC chapters.c)
add_library(ermao_chapters_shared SHARED chapters.c)

foreach(target ermao_chapters ermao_chapters_shared)
    target_include_directories(${target}
        PUBLIC
            ${CMAKE_CURRENT_SOURCE_DIR}/include
    )
    target_compile_features(${target} PUBLIC c_std_99)
    target_compile_options(${target} PRIVATE ${ERMAO_CHAPTERS_WARNING_OPTIONS})
    set_target_properties(${target} PROPERTIES POSITION_INDEPENDENT_CODE ON)
endforeach()

set_target_properties(ermao_chapters_shared PROPERTIES
    OUTPUT_NAME ermao_chapters
    WINDOWS_EXPORT_ALL_SYMBOLS ON
)

include(CTest)
if(BUILD_TESTING)
    add_executable(ermao_chapters_tests tests/test_chapters.c)
    target_include_directories(ermao_chapters_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
    target_compile_features(ermao_chapters_tests PRIVATE c_std_99)
    target_compile_options(ermao_chapters_tests PRIVATE ${ERMAO_CHAPTERS_WARNING_OPTIONS})
    target_link_libraries(ermao_chapters_tests PRIVATE ermao_chapters)
    add_test(NAME ermao_chapters_tests COMMAND ermao_chapters_tests)
endif()
