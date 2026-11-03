// Where typing starts (UX-018): a field takes the focus only where that opens no on-screen keyboard.

/** Whether the device has a mouse or trackpad, rather than only a touch screen. */
export function hasKeyboard(): boolean {
  return !window.matchMedia("(hover: none)").matches;
}
