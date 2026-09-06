cmake_minimum_required(VERSION 3.22)
project(ermao_chapters_web LANGUAGES C)

if(NOT EMSCRIPTEN)
  message(FATAL_ERROR "ermao_chapters_web must be configured with emcmake (Emscripten 3.1.74)")
endif()

set(ERMAO_CHAPTER_CORE_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../packages/reader-core/native/chapters")
add_subdirectory("${ERMAO_CHAPTER_CORE_ROOT}" "${CMAKE_CURRENT_BINARY_DIR}/chapter-core")

if(TARGET Ermao::ChaptersCore)
  set(ERMAO_CHAPTER_CORE_TARGET Ermao::ChaptersCore)
elseif(TARGET ermao_chapters_core)
  set(ERMAO_CHAPTER_CORE_TARGET ermao_chapters_core)
elseif(TARGET Ermao::ChapterCore)
  set(ERMAO_CHAPTER_CORE_TARGET Ermao::ChapterCore)
elseif(TARGET ermao_chapter_core)
  set(ERMAO_CHAPTER_CORE_TARGET ermao_chapter_core)
elseif(TARGET ermao_chapters)
  set(ERMAO_CHAPTER_CORE_TARGET ermao_chapters)
else()
  message(FATAL_ERROR "The chapter core must export Ermao::ChaptersCore or ermao_chapters")
endif()

add_executable(ermao_chapters_web web_entry.c)
target_link_libraries(ermao_chapters_web PRIVATE "${ERMAO_CHAPTER_CORE_TARGET}")
target_include_directories(ermao_chapters_web PRIVATE "${ERMAO_CHAPTER_CORE_ROOT}/include")
set_target_properties(ermao_chapters_web PROPERTIES OUTPUT_NAME "ermao-chapters" SUFFIX ".mjs")

set(ERMAO_CHAPTER_EXPORTED_FUNCTIONS
  "['_malloc','_free','_ermao_chapters_abi_version','_ermao_chapters_parse_txt','_ermao_chapters_parse_xml','_ermao_chapters_from_mobi','_ermao_chapters_count','_ermao_chapters_navigable_count','_ermao_chapters_entry','_ermao_chapters_text','_ermao_chapters_text_length','_ermao_chapters_free','_ermao_chapters_web_copy_entry','_ermao_chapters_web_copy_text_length']"
)
target_link_options(ermao_chapters_web PRIVATE
  "--no-entry"
  "-sMODULARIZE=1"
  "-sEXPORT_ES6=1"
  "-sEXPORT_NAME=createErmaoChaptersModule"
  "-sENVIRONMENT=web,worker"
  "-sALLOW_MEMORY_GROWTH=1"
  "-sINITIAL_MEMORY=16777216"
  "-sMAXIMUM_MEMORY=268435456"
  "-sNO_EXIT_RUNTIME=1"
  "-sASSERTIONS=0"
  "-sEXPORTED_FUNCTIONS=${ERMAO_CHAPTER_EXPORTED_FUNCTIONS}"
  "-sEXPORTED_RUNTIME_METHODS=['ccall','getValue','setValue']"
)
