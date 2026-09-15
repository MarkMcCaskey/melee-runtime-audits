/* Executes in Melee's initialized main thread. No SDK/save routine is replaced.
 * Function addresses come from the matching ELF via compiler -D arguments.
 * The host uses the mailbox only while ready != 1. */
typedef unsigned int u32;
typedef int s32;
typedef void (*Callback)(s32, s32);
struct State;
struct FileInfo;
struct Mailbox {
    volatile u32 ready;
    volatile u32 operation;
    volatile u32 args[6];
    volatile s32 result;
    volatile u32 magic;
};
#define MAILBOX ((struct Mailbox*) 0x81001000)
#define COMPLETION ((volatile s32*) 0x81001800)
#define FN(name, result, ...) ((result (*)(__VA_ARGS__)) name##_ADDR)
#define POINTER(index) ((void*) box->args[index])

enum Operation {
    PROBE = 1, MOUNT, CHECK, RESET_QUEUE, INIT_STATE, REGISTER_FILE, BLOCK_COUNT,
    CREATE_SAVE, READ_FILE, WRITE_FILE, OPEN_SAVE, READ_HEADER, UPDATE_HEADER,
    UNMOUNT, WAIT_CALLBACK, DRAIN, CREATE_RAW
};

void callback(s32 argument, s32 result)
{
    COMPLETION[1] = argument;
    COMPLETION[2] = result;
    COMPLETION[0] = 1;
}

static __attribute__((always_inline)) inline s32 dispatch(struct Mailbox* box)
{
    switch (box->operation) {
    case PROBE:
        return FN(CARDProbeEx, s32, s32, s32*, s32*)(
            0, POINTER(0), POINTER(1));
    case MOUNT:
        return FN(CARDMountAsync, s32, s32, void*, Callback, Callback)(
            0, POINTER(0), (Callback) 0, (Callback) box->args[1]);
    case CHECK:
        return FN(CARDCheckAsync, s32, s32, Callback)(0, (Callback) box->args[0]);
    case RESET_QUEUE:
        FN(hsd_803B2374, void, void)();
        return 0;
    case INIT_STATE:
        FN(hsd_803B24E4, void, struct State*, int, int, void*)(
            POINTER(0), 0, 8192, POINTER(1));
        return 0;
    case REGISTER_FILE:
        FN(hsd_803AC3E0, void, struct State*, int, int, int, void*)(
            POINTER(0), box->args[1], box->args[2], box->args[3], POINTER(4));
        return 0;
    case BLOCK_COUNT:
        return FN(hsd_803B2674, int, struct State*)(POINTER(0));
    case CREATE_SAVE:
        return FN(hsd_803B286C, int, struct State*, const char*, const char*,
                  void*, void*, Callback)(POINTER(0), POINTER(1), POINTER(2),
                                         (void*) 0, (void*) 0,
                                         (Callback) box->args[3]);
    case READ_FILE:
        return FN(hsd_803B29D8, int, struct State*, int, unsigned char*, Callback)(
            POINTER(0), box->args[1], POINTER(2), (Callback) box->args[3]);
    case WRITE_FILE:
        return FN(hsd_803B2A4C, int, struct State*, int, unsigned char*, Callback)(
            POINTER(0), box->args[1], POINTER(2), (Callback) box->args[3]);
    case OPEN_SAVE:
        return FN(hsd_803B2550, int, struct State*, const char*, Callback)(
            POINTER(0), POINTER(1), (Callback) box->args[2]);
    case READ_HEADER:
        return FN(hsd_803B27F4, int, struct State*, void*, void*, void*, Callback)(
            POINTER(0), POINTER(1), (void*) 0, (void*) 0, (Callback) box->args[2]);
    case UPDATE_HEADER:
        return FN(hsd_803B2928, int, struct State*, const char*, void*, void*, Callback)(
            POINTER(0), POINTER(1), (void*) 0, (void*) 0, (Callback) box->args[2]);
    case UNMOUNT:
        return FN(CARDUnmount, s32, s32)(0);
    case WAIT_CALLBACK:
        while (COMPLETION[0] != 1) {}
        return 0;
    case DRAIN:
        do {
            FN(hsd_803AAA48, void, void)();
        } while (*(volatile s32*) hsd_804D799C_ADDR != 2);
        return 0;
    case CREATE_RAW:
        return FN(CARDCreateAsync, s32, s32, const char*, u32, struct FileInfo*, Callback)(
            0, POINTER(0), box->args[1], POINTER(2), (Callback) box->args[3]);
    default:
        return -0x3489;
    }
}

void driver(void)
{
    struct Mailbox* box = MAILBOX;
    box->magic = 0x34890001;
    for (;;) {
        if (box->ready == 1) {
            box->result = dispatch(box);
            box->ready = 2;
        }
    }
}
