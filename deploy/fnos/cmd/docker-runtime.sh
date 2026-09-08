#!/bin/bash

# Shared, read-only container discovery for status and installation safety.
web_container_states() {
  docker ps --all \
    --filter "label=com.docker.compose.project=ermao-books" \
    --filter "label=com.docker.compose.service=web" \
    --format '{{.State}}' 2>/dev/null
}
