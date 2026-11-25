/* Fake data for the UI prototype. Replaced by API calls later. */

const PEOPLE = [
  { name: "Abel", job: "Painter" }, { name: "Bea", job: "Quarryman" },
  { name: "Clara", job: "Ranger" }, { name: "Derek", job: "Sailor" },
  { name: "Eliza", job: "Tailor" }, { name: "Franz", job: "Usher" },
  { name: "Grant", job: "Vet" }, { name: "Hannah", job: "Writer" },
  { name: "Ivy", job: "Xenobiologist" }, { name: "Jonas", job: "Astronaut" },
  { name: "Karl", job: "Cook" }, { name: "Leo", job: "Detective" },
  { name: "Mara", job: "Clerk" }, { name: "Noah", job: "Farmer" },
  { name: "Owen", job: "Guard" }, { name: "Priya", job: "Baker" },
  { name: "Quilla", job: "Carpenter" }, { name: "Roy", job: "Dancer" },
  { name: "Sophia", job: "Engineer" }, { name: "Tom", job: "Fisher" },
  { name: "Uma", job: "Gardener" }, { name: "Victor", job: "Hunter" },
  { name: "Wendy", job: "Inventor" }, { name: "Xavier", job: "Judge" },
  { name: "Yara", job: "Knight" },
];

/* "unknown" = face-down, "innocent" = civilian, "criminal" */
const STATUS = [
  "innocent", "criminal", "unknown", "unknown", "innocent",
  "unknown", "criminal", "unknown", "innocent", "unknown",
  "innocent", "unknown", "criminal", "unknown", "innocent",
  "unknown", "unknown", "criminal", "unknown", "innocent",
  "innocent", "unknown", "unknown", "criminal", "unknown",
];

/* shown on a tile only when it is revealed */
const CLUES = [
  "Abel and Bea have different statuses.",
  "Exactly 1 criminal in C1 and A1.",
  "Derek is innocent.",
  "Eliza and Abel have the same status.",
  "Franz is innocent.",
  "Grant is a criminal.",
  "No criminals in B3 and B1.",
  "Exactly 2 criminals in C3, A2, C1, A3.",
  "Exactly 2 criminals in the neighbours of B1.",
  "At least 1 criminal in row 2.",
  "The number of criminals in column B is odd.",
  "Row 1 has fewer criminals than column C.",
  "At most 2 criminals in the neighbours of C3.",
  "Exactly 3 criminals on the boundary.",
  "Jonas and Karl have different statuses.",
  "Leo is a criminal.",
  "No criminals in the four corners.",
  "At least 2 criminals in row 4.",
  "Mara and Noah have the same status.",
  "The number of criminals in row 5 is even.",
  "Exactly 1 criminal in the neighbours of A1.",
  "Priya is innocent.",
  "Roy is a criminal.",
  "Exactly 2 criminals in column D.",
  "Tom and Uma have different statuses.",
];

const LEVELS = [
  { id: "G01", size: 3, difficulty: "easy" },
  { id: "G02", size: 3, difficulty: "medium" },
  { id: "G03", size: 3, difficulty: "hard" },
  { id: "G04", size: 4, difficulty: "easy" },
  { id: "G05", size: 4, difficulty: "medium" },
  { id: "G06", size: 4, difficulty: "hard" },
  { id: "G07", size: 5, difficulty: "medium" },
  { id: "GEN-3x3-easy-42", size: 3, difficulty: "easy" },
  { id: "GEN-4x4-hard-7", size: 4, difficulty: "hard" },
  { id: "GEN-5x5-hard-123", size: 5, difficulty: "hard" },
];

/* the tile whose details are shown in the Game panel (until selection is wired up) */
const SAMPLE = {
  index: 1,
  targets: [{ cell: "C1", role: "target" }, { cell: "A1", role: "target" }],
  mentions: [{ by: 0 }, { by: 8 }],
};