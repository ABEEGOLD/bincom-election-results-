// Chained dropdowns: when the first <select> changes, fill the second from the server.
function fillSelect(select, items, placeholder) {
  select.innerHTML = "";
  const first = document.createElement("option");
  first.value = "";
  first.textContent = placeholder;
  select.appendChild(first);
  items.forEach(function (item) {
    const option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;   // textContent, never innerHTML, so names can't inject HTML
    select.appendChild(option);
  });
}

document.addEventListener("DOMContentLoaded", function () {
  const parent = document.querySelector("select[data-target]");
  if (parent) {
    const child = document.getElementById(parent.dataset.target);
    parent.addEventListener("change", async function () {
      if (!parent.value) {
        fillSelect(child, [], "Select a local government first...");
        child.disabled = true;
        return;
      }
      child.disabled = true;
      fillSelect(child, [], "Loading...");
      try {
        const response = await fetch(parent.dataset.source + "?lga_id=" + encodeURIComponent(parent.value));
        const items = await response.json();
        fillSelect(child, items, items.length ? "Select one..." : "Nothing available");
        child.disabled = items.length === 0;
      } catch (error) {
        fillSelect(child, [], "Could not load, try again");
      }
    });
  }

  // The LGA total page reloads as soon as an LGA is picked.
  const auto = document.querySelector("select[data-autosubmit]");
  if (auto) {
    auto.addEventListener("change", function () {
      if (auto.value) auto.form.submit();
    });
  }
});
