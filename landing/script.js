/* ─── Scroll Reveal ─────────────────────────────────────────────── */
const revealEls = document.querySelectorAll('.step, .card, .pricing-card');

const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry, i) => {
    if (entry.isIntersecting) {
      // Stagger animation
      setTimeout(() => {
        entry.target.classList.add('visible');
      }, i * 80);
      revealObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.15 });

revealEls.forEach(el => {
  el.classList.add('reveal');
  revealObserver.observe(el);
});

/* ─── Nav scroll effect ─────────────────────────────────────────── */
const nav = document.querySelector('.nav');

window.addEventListener('scroll', () => {
  if (window.scrollY > 40) {
    nav.style.borderBottomColor = 'rgba(99,102,241,0.2)';
  } else {
    nav.style.borderBottomColor = 'rgba(255,255,255,0.06)';
  }
}, { passive: true });

/* ─── Modal Logic ───────────────────────────────────────────────── */
const modal     = document.getElementById('modal');
const ctaBtn    = document.getElementById('ctaBtn');
const closeBtn  = document.getElementById('modalClose');
const emailForm = document.getElementById('emailForm');
const emailInput = document.getElementById('emailInput');
const modalNote = document.getElementById('modalNote');

function openModal() {
  modal.classList.add('active');
  document.body.style.overflow = 'hidden';
  setTimeout(() => emailInput.focus(), 100);
}

function closeModal() {
  modal.classList.remove('active');
  document.body.style.overflow = '';
  modalNote.textContent = '';
  emailInput.value = '';
}

ctaBtn.addEventListener('click', openModal);

// Also open modal on all "Start Free" buttons
document.querySelectorAll('.btn-outline, .btn-primary').forEach(btn => {
  if (btn.textContent.trim() === 'Start Free') {
    btn.addEventListener('click', openModal);
  }
});

closeBtn.addEventListener('click', closeModal);

modal.addEventListener('click', (e) => {
  if (e.target === modal) closeModal();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && modal.classList.contains('active')) {
    closeModal();
  }
});

emailForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const email = emailInput.value.trim();
  if (!email) return;

  // Simulate submission
  modalNote.textContent = 'Sending...';
  setTimeout(() => {
    modalNote.textContent = '✓ You\'re on the list! We\'ll be in touch soon.';
    emailInput.value = '';
    setTimeout(closeModal, 1800);
  }, 800);
});
