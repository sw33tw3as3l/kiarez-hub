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

export function randomFunLabel(): string {
  return FUN_LABELS[Math.floor(Math.random() * FUN_LABELS.length)];
}
