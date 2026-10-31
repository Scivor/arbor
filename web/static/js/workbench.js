'use strict';
const rows = [...document.querySelectorAll('[data-lot]')];
const search = document.querySelector('#search');
let filter = 'all';
function applyFilter() {
  let count = 0;
  rows.forEach(row => {
    const matches = row.textContent.toLowerCase().includes(search.value.trim().toLowerCase());
    row.hidden = !matches || filter === 'near' || (filter === 'limited' && row.dataset.lot !== '002');
    if (!row.hidden) count++;
  });
  document.querySelector('#no-results').hidden = count !== 0;
  document.querySelector('#result-count').textContent = `显示 ${count} 个批次`;
}
document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
  filter = button.dataset.filter;
  document.querySelectorAll('[data-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  applyFilter();
}));
search.addEventListener('input', applyFilter);
let selected = '002';
const toggle = document.querySelector('#preview-toggle');
const preview = document.querySelector('#preview');
function selectLot(id) {
  selected = id;
  rows.forEach(row => row.classList.toggle('selected', row.dataset.lot === id));
  document.querySelectorAll('[data-select]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.select === id)));
  document.querySelector('#lot-title').textContent = `DEMO-LOT-${id}`;
  document.querySelector('#lot-contracts').textContent = id === '001' ? '2 手' : '1 手';
  preview.hidden = true;
  toggle.setAttribute('aria-expanded', 'false');
}
function showPreview() {
  document.querySelector('#preview-message').textContent = selected === '001' ? '当前已达到 2 手目标，无需新增仓位。' : '预算不足以新增一手，保留当前 1 手；目标仍差 1 手。';
  preview.hidden = false;
  toggle.setAttribute('aria-expanded', 'true');
}
document.querySelectorAll('[data-select]').forEach(button => button.addEventListener('click', () => selectLot(button.dataset.select)));
toggle.addEventListener('click', () => {
  if (preview.hidden) showPreview();
  else { preview.hidden = true; toggle.setAttribute('aria-expanded', 'false'); }
});
document.querySelector('#alert-preview').addEventListener('click', () => {
  selectLot('002'); showPreview(); toggle.scrollIntoView({block:'center'}); toggle.focus();
});
