#define _POSIX_C_SOURCE 200809L
#define SN_API_NOT_YET_FROZEN

#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <libsn/sn.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

static int
read_cardinal(Display *display, Window window, Atom property, unsigned long *value)
{
  Atom actual_type;
  int actual_format;
  unsigned long count;
  unsigned long remaining;
  unsigned char *data = NULL;
  int status = XGetWindowProperty(display, window, property, 0, 1, False,
                                  XA_CARDINAL, &actual_type, &actual_format,
                                  &count, &remaining, &data);

  if (status != Success || actual_type != XA_CARDINAL || actual_format != 32 ||
      count != 1 || data == NULL) {
    if (data != NULL) {
      XFree(data);
    }
    return 0;
  }

  *value = *(unsigned long *)data;
  XFree(data);
  return 1;
}

static int
window_matches(Display *display, Window window, Atom pid_atom, pid_t pid)
{
  XClassHint hint;
  unsigned long window_pid;
  int class_matches = 0;

  if (!read_cardinal(display, window, pid_atom, &window_pid) ||
      window_pid != (unsigned long)pid) {
    return 0;
  }

  memset(&hint, 0, sizeof(hint));
  if (XGetClassHint(display, window, &hint)) {
    class_matches =
      (hint.res_name != NULL && strcmp(hint.res_name, "resolve") == 0) ||
      (hint.res_class != NULL && strcmp(hint.res_class, "resolve") == 0);
    if (hint.res_name != NULL) {
      XFree(hint.res_name);
    }
    if (hint.res_class != NULL) {
      XFree(hint.res_class);
    }
  }

  return class_matches;
}

static Window
find_window(Display *display, Window root, Atom client_list_atom, Atom pid_atom,
            pid_t pid)
{
  Atom actual_type;
  int actual_format;
  unsigned long count;
  unsigned long remaining;
  unsigned char *data = NULL;
  Window match = None;
  int status = XGetWindowProperty(display, root, client_list_atom, 0, 4096,
                                  False, XA_WINDOW, &actual_type, &actual_format,
                                  &count, &remaining, &data);

  if (status != Success || actual_type != XA_WINDOW || actual_format != 32 ||
      data == NULL) {
    if (data != NULL) {
      XFree(data);
    }
    return None;
  }

  Window *windows = (Window *)data;
  for (unsigned long index = 0; index < count; index++) {
    if (window_matches(display, windows[index], pid_atom, pid)) {
      match = windows[index];
      break;
    }
  }

  XFree(data);
  return match;
}

static void
monitor_startup(pid_t resolve_pid)
{
  const char *startup_id = getenv("DESKTOP_STARTUP_ID");
  if (startup_id == NULL || *startup_id == '\0') {
    fprintf(stderr, "resolve-startup-bridge: no DESKTOP_STARTUP_ID; nothing to complete\n");
    _exit(0);
  }

  Display *display = XOpenDisplay(NULL);
  if (display == NULL) {
    fprintf(stderr, "resolve-startup-bridge: cannot open X display\n");
    _exit(1);
  }

  int screen = DefaultScreen(display);
  Window root = RootWindow(display, screen);
  Atom client_list_atom = XInternAtom(display, "_NET_CLIENT_LIST", False);
  Atom pid_atom = XInternAtom(display, "_NET_WM_PID", False);
  SnDisplay *sn_display = sn_display_new(display, NULL, NULL);
  SnLauncheeContext *context =
    sn_launchee_context_new(sn_display, screen, startup_id);
  struct timespec delay = {.tv_sec = 0, .tv_nsec = 50000000};

  for (int attempt = 0; attempt < 300; attempt++) {
    Window window = find_window(display, root, client_list_atom, pid_atom,
                                resolve_pid);
    if (window != None) {
      sn_launchee_context_setup_window(context, window);
      sn_launchee_context_complete(context);
      XSync(display, False);
      fprintf(stderr,
              "resolve-startup-bridge: completed startup id for pid %ld window 0x%lx\n",
              (long)resolve_pid, (unsigned long)window);
      sn_launchee_context_unref(context);
      sn_display_unref(sn_display);
      XCloseDisplay(display);
      _exit(0);
    }

    if (kill(resolve_pid, 0) != 0 && errno == ESRCH) {
      break;
    }
    nanosleep(&delay, NULL);
  }

  fprintf(stderr,
          "resolve-startup-bridge: no matching Resolve window for pid %ld within 15 seconds\n",
          (long)resolve_pid);
  sn_launchee_context_unref(context);
  sn_display_unref(sn_display);
  XCloseDisplay(display);
  _exit(1);
}

int
main(int argc, char **argv)
{
  pid_t resolve_pid = getpid();
  pid_t monitor_pid = fork();

  if (monitor_pid < 0) {
    perror("resolve-startup-bridge: fork");
    return 1;
  }
  if (monitor_pid == 0) {
    monitor_startup(resolve_pid);
  }

  char *const resolve_argv[] = {
    "/usr/sbin/switcherooctl",
    "launch",
    "/usr/bin/env",
    "ALSA_CONFIG_PATH=/etc/alsa/resolve.conf",
    "/opt/resolve/bin/resolve",
    argc > 1 ? argv[1] : NULL,
    NULL,
  };

  execv(resolve_argv[0], resolve_argv);
  perror("resolve-startup-bridge: execv");
  return 1;
}
