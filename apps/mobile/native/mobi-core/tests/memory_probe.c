#include "ermao_mobi.h"
#include "mobi.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/time.h>

static uint64_t elapsed_milliseconds(const struct timeval *started) {
    struct timeval finished;
    gettimeofday(&finished, NULL);
    const uint64_t started_us = (uint64_t) started->tv_sec * 1000000u
        + (uint64_t) started->tv_usec;
    const uint64_t finished_us = (uint64_t) finished.tv_sec * 1000000u
        + (uint64_t) finished.tv_usec;
    return (finished_us - started_us) / 1000u;
}

static long current_rss_kilobytes(void) {
    FILE *status = fopen("/proc/self/status", "r");
    if (status == NULL) {
        return -1;
    }
    char line[256];
    long rss = -1;
    while (fgets(line, sizeof(line), status) != NULL) {
        if (sscanf(line, "VmRSS: %ld kB", &rss) == 1) {
            break;
        }
    }
    fclose(status);
    return rss;
}

static long peak_rss_kilobytes(void) {
    struct rusage usage;
    return getrusage(RUSAGE_SELF, &usage) == 0 ? usage.ru_maxrss : -1;
}

static void print_stage(const char *stage, uint64_t elapsed_ms) {
    printf(
        "%s\telapsed_ms=%" PRIu64 "\tcurrent_rss_kb=%ld\tpeak_rss_kb=%ld\n",
        stage,
        elapsed_ms,
        current_rss_kilobytes(),
        peak_rss_kilobytes()
    );
}

static int probe_upstream(const char *path) {
    MOBIData *mobi = mobi_init();
    if (mobi == NULL) {
        return 1;
    }
    struct timeval started;
    gettimeofday(&started, NULL);
    const MOBI_RET load_result = mobi_load_filename(mobi, path);
    print_stage("mobi_load_filename", elapsed_milliseconds(&started));
    if (load_result != MOBI_SUCCESS) {
        mobi_free(mobi);
        return 1;
    }

    MOBIRawml *rawml = mobi_init_rawml(mobi);
    if (rawml == NULL) {
        mobi_free(mobi);
        return 1;
    }
    gettimeofday(&started, NULL);
    const MOBI_RET rawml_result = mobi_parse_rawml(rawml, mobi);
    print_stage("mobi_parse_rawml", elapsed_milliseconds(&started));
    mobi_free_rawml(rawml);
    mobi_free(mobi);
    print_stage("upstream_close", 0u);
    return rawml_result == MOBI_SUCCESS ? 0 : 1;
}

static int probe_abi(const char *path) {
    ErmaoMobiBook *book = NULL;
    struct timeval started;
    gettimeofday(&started, NULL);
    const ErmaoMobiStatus open_result = ermao_mobi_open(path, NULL, &book);
    print_stage("ermao_open_and_index", elapsed_milliseconds(&started));
    if (open_result != ERMAO_MOBI_OK) {
        return 1;
    }
    ErmaoMobiBookInfo info = {.struct_size = sizeof(info)};
    if (ermao_mobi_get_book_info(book, &info) != ERMAO_MOBI_OK
        || info.reading_order_count == 0u) {
        ermao_mobi_close(&book);
        return 1;
    }
    uint32_t resource_index = 0u;
    if (ermao_mobi_reading_order_resource_index(book, 0u, &resource_index)
        != ERMAO_MOBI_OK) {
        ermao_mobi_close(&book);
        return 1;
    }
    uint8_t first_chunk[4096];
    uint32_t bytes_read = 0u;
    gettimeofday(&started, NULL);
    const ErmaoMobiStatus read_result = ermao_mobi_read_resource(
        book,
        resource_index,
        0u,
        first_chunk,
        sizeof(first_chunk),
        &bytes_read
    );
    print_stage("ermao_first_chunk", elapsed_milliseconds(&started));
    ermao_mobi_close(&book);
    print_stage("ermao_close", 0u);
    return read_result == ERMAO_MOBI_OK && bytes_read > 0u ? 0 : 1;
}

int main(int argc, char **argv) {
    if (argc != 3 || (strcmp(argv[1], "upstream") != 0 && strcmp(argv[1], "abi") != 0)) {
        fprintf(stderr, "usage: %s <upstream|abi> <publication>\n", argv[0]);
        return 2;
    }
    print_stage("start", 0u);
    return strcmp(argv[1], "upstream") == 0
        ? probe_upstream(argv[2])
        : probe_abi(argv[2]);
}
