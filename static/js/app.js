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
