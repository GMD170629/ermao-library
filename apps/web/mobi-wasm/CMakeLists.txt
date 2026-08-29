cmake_minimum_required(VERSION 3.22)
project(ermao_mobi_web LANGUAGES C)

if(NOT EMSCRIPTEN)
  message(FATAL_ERROR "ermao_mobi_web must be configured with emcmake (Emscripten 3.1.74)")
endif()

set(ERMAO_MOBI_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(ERMAO_MOBI_ENABLE_SANITIZERS OFF CACHE BOOL "" FORCE)
set(ERMAO_MOBI_BUILD_FUZZER OFF CACHE BOOL "" FORCE)
set(ERMAO_MOBI_CORE_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../mobile/native/mobi-core")
add_subdirectory("${ERMAO_MOBI_CORE_ROOT}" "${CMAKE_CURRENT_BINARY_DIR}/mobi-core")
# Emscripten lowers both STATIC and SHARED libraries to archives. The native
# project intentionally gives them the same basename, so disambiguate only the
# unused Web-side shared target without changing the authoritative core build.
set_target_properties(ermao_mobi_core_shared PROPERTIES OUTPUT_NAME "ermao_mobi_core_shared")
target_compile_definitions(ermao_mobi_core PRIVATE _GNU_SOURCE)

add_executable(ermao_mobi_web web_entry.c)
target_link_libraries(ermao_mobi_web PRIVATE Ermao::MobiCore)
target_include_directories(ermao_mobi_web PRIVATE "${ERMAO_MOBI_CORE_ROOT}/Sources/CLibMobi/public")
set_target_properties(ermao_mobi_web PROPERTIES OUTPUT_NAME "ermao-mobi" SUFFIX ".mjs")

set(ERMAO_EXPORTED_FUNCTIONS
  "['_malloc','_free','_ermao_mobi_abi_version','_ermao_mobi_parser_identifier','_ermao_mobi_normalization_identifier','_ermao_mobi_status_name','_ermao_mobi_default_options','_ermao_mobi_open','_ermao_mobi_close','_ermao_mobi_get_book_info','_ermao_mobi_copy_metadata','_ermao_mobi_get_resource_info','_ermao_mobi_copy_resource_source_name','_ermao_mobi_copy_resource_media_type','_ermao_mobi_web_read_resource','_ermao_mobi_reading_order_count','_ermao_mobi_reading_order_resource_index','_ermao_mobi_toc_count','_ermao_mobi_get_toc_info','_ermao_mobi_copy_toc_title','_ermao_mobi_copy_toc_fragment']"
)
target_link_options(ermao_mobi_web PRIVATE
  "--no-entry"
  "-sMODULARIZE=1"
  "-sEXPORT_ES6=1"
  "-sEXPORT_NAME=createErmaoMobiModule"
  "-sENVIRONMENT=worker"
  "-sFILESYSTEM=1"
  "-lworkerfs.js"
  "-sALLOW_MEMORY_GROWTH=1"
  "-sINITIAL_MEMORY=67108864"
  "-sMAXIMUM_MEMORY=2415919104"
  "-sSTACK_SIZE=1048576"
  "-sNO_EXIT_RUNTIME=1"
  "-sASSERTIONS=0"
  "-sEXPORTED_FUNCTIONS=${ERMAO_EXPORTED_FUNCTIONS}"
  "-sEXPORTED_RUNTIME_METHODS=['FS','ccall','getValue','setValue','UTF8ToString']"
)
