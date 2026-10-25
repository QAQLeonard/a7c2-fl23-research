/* Identical file entry, explicit fixture directory, constructor disabled. */
#include "file_entry.h"
#include <stdio.h>
int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    int status = a7_file_entry_run(argv[1]);
    printf("{\"status\":%d,\"camera_io\":false}\n", status);
    return 0;
}
