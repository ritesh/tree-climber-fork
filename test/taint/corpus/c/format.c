/*
 * Format strings with the built-in C rules: untrusted data as the format of
 * `printf`, `fprintf`, `sprintf`, `snprintf` and `syslog` is a finding, as an
 * argument after a constant format it is not.
 */
#include <stdio.h>
#include <stdlib.h>
#include <syslog.h>

void log_message(const char *message) {
    // ruleid: c-format-string
    syslog(LOG_INFO, message);
    // ok: c-format-string
    syslog(LOG_INFO, "%s", message);
}

int main(int argc, char **argv) {
    const char *home = getenv("HOME");
    char buffer[256];

    // ruleid: c-format-string
    printf(home);
    // ok: c-format-string
    printf("%s\n", home);
    // ruleid: c-format-string
    fprintf(stderr, argv[1]);
    // ok: c-format-string
    fprintf(stderr, "%s", argv[1]);
    // ruleid: c-format-string
    sprintf(buffer, argv[1]);
    // ruleid: c-format-string
    snprintf(buffer, sizeof buffer, home);
    // ok: c-format-string
    snprintf(buffer, sizeof buffer, "%s", home);

    log_message(argv[2]);
    return 0;
}
