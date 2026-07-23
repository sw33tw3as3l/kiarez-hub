export const FUN_LABELS = [
  "Hi KiaRez",
  "What's up?",
  "You got this",
  "Keep going",
  "Focus time",
  "Let's go",
  "One step at a time",
  "Nice work",
];

export function funLabelFor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) | 0;
  }
  return FUN_LABELS[Math.abs(hash) % FUN_LABELS.length];
}
