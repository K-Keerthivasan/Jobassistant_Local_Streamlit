async function send(op) {
  const r = await chrome.runtime.sendMessage({
    op,
    applicationId: document.getElementById("application").value.trim(),
  });
  document.getElementById("status").textContent =
    r.error ||
    `Extension ID: ${r.id}\n${r.connected ? "Connected" : "Disconnected"}\nActive: ${r.session?.applicationId || "none"}`;
}
document.getElementById("connect").onclick = () => send("connect");
document.getElementById("adopt").onclick = () => send("adopt");
send("status");
