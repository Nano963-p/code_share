function qs(id){ return document.getElementById(id); }

function openOverlay(){
  const ov = qs("modal-overlay");
  if (ov) ov.classList.remove("hidden");
}

function closeOverlay(){
  const ov = qs("modal-overlay");
  if (ov) ov.classList.add("hidden");
}

function openCreateProject(){
  const m = qs("create-project-modal");
  if (!m) return;
  openOverlay();
  m.classList.remove("hidden");

  // focus first input (title)
  const inp = m.querySelector('input[name="title"]');
  if (inp) setTimeout(() => inp.focus(), 50);
}

function closeAllModals(){
  const m = qs("create-project-modal");
  if (m) m.classList.add("hidden");
  closeOverlay();
}

function toggleBox(id){
  const el = qs(id);
  if (!el) return;
  el.classList.toggle("hidden");
}

// ESC closes modals
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeAllModals();
});

// Tag picker (project page): filter chips by text
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-tag-manager]").forEach((mgr) => {
    const inp = mgr.querySelector("[data-tag-filter]");
    const list = mgr.querySelector("[data-tag-list]");
    if (!inp || !list) return;

    const items = Array.from(list.querySelectorAll("[data-tag-name]"));

    function applyFilter(){
      const q = (inp.value || "").trim().toLowerCase();
      items.forEach((el) => {
        const name = (el.getAttribute("data-tag-name") || "");
        el.style.display = (!q || name.includes(q)) ? "inline-flex" : "none";
      });
    }

    inp.addEventListener("input", applyFilter);
  });
});
