cmake_minimum_required(VERSION 3.22)
project(readium_web_poc_server LANGUAGES C)

set(ERMAO_MOBI_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(ERMAO_MOBI_BUILD_FUZZER OFF CACHE BOOL "" FORCE)
add_subdirectory(
  "${CMAKE_CURRENT_SOURCE_DIR}/../../mobile/native/mobi-core"
  "${CMAKE_CURRENT_BINARY_DIR}/mobi-core"
)

add_executable(readium_web_poc_server main.c)
target_compile_features(readium_web_poc_server PRIVATE c_std_99)
target_compile_options(readium_web_poc_server PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_link_libraries(readium_web_poc_server PRIVATE Ermao::MobiCore)
