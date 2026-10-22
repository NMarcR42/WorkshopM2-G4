// L'API ne stocke pas de libellé sur une transaction (contrat inchangé). On garde donc le nom de l'article
// payé côté navigateur, par identifiant de transaction, uniquement pour l'affichage de l'historique.
// localStorage peut être indisponible (navigation privée) : on ignore alors l'erreur, l'historique reste lisible.
const KEY = 'tx-labels'

function read() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) ?? {}
  } catch {
    return {}
  }
}

export const labelOf = (id) => read()[id]

export function saveLabel(id, label) {
  try {
    const all = read()
    all[id] = label
    // On borne la taille : seules les dernières transactions sont affichées.
    const keep = Object.fromEntries(Object.entries(all).slice(-200))
    localStorage.setItem(KEY, JSON.stringify(keep))
  } catch {
    /* sans stockage, pas de libellé : sans gravité */
  }
}
