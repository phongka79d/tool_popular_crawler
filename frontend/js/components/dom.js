/** Create an element with text-safe children (strings or Nodes). */
export function el(tag, className = "", ...children) {
  const node = document.createElement(tag);
  node.className = className;
  append(node, ...children);
  return node;
}
export function append(node, ...children) {
  for (const child of children.flat(1 / 0))
    if (child !== null && child !== undefined && child !== false)
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}
/** Decorate field wrappers with input access and a live value property. */
export function bindField(wrapper, input, { label, hint, onChange, event = "input", read = () => input.value, write = (v) => {
  input.value = v ?? "";
} } = {}) {
  const id = input.id || `field-${++bindField.id}`;
  input.id = id;
  if (label) {
    const l = el("label", "field-label", label);
    l.htmlFor = id;
    wrapper.prepend(l);
  }
  if (hint) {
    const help = el("div", "hint", hint);
    help.id = `${id}-hint`;
    input.setAttribute("aria-describedby", help.id);
    wrapper.append(help);
  }
  wrapper.input = input;
  Object.defineProperty(wrapper, "value", { get: read, set: write });
  if (onChange)
    input.addEventListener(event, (e) => onChange(read(), e));
  return wrapper;
}
bindField.id = 0;
