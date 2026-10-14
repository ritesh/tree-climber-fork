const SAMPLES: Record<string, string> = {
  c: `// Example code
int main() {
    int a;
    if (a > 10) {
        for (int i = 0; i < 10; i ++) {
            a ++;
        }
    }
    return a;
}
`,
  java: `// Example code
public class Example {
    public static int count(int a) {
        if (a > 10) {
            for (int i = 0; i < 10; i++) {
                a++;
            }
        }
        return a;
    }
}
`,
  python: `# Example code
import os


def count(a):
    if a > 10:
        for i in range(10):
            a += 1
    return a


def ping():
    host = input()
    run("ping -c 1 " + host)


def run(command):
    os.system(command)
`,
};

// Before per-language buffers, one buffer was shared under this key.
const LEGACY_KEY = 'tree_climber_code';

const keyFor = (language: string) => `tree_climber_code_${language}`;

export function sampleCode(language: string): string {
  return SAMPLES[language] ?? SAMPLES.c;
}

// Each language keeps its own code, so switching language shows that language's code
// (or its sample) instead of parsing, say, C as Python.
export function loadCode(language: string): string {
  const stored = localStorage.getItem(keyFor(language));
  if (stored) {
    return stored;
  }
  const legacy = localStorage.getItem(LEGACY_KEY);
  if (legacy) {
    localStorage.setItem(keyFor(language), legacy);
    localStorage.removeItem(LEGACY_KEY);
    return legacy;
  }
  return sampleCode(language);
}

export function saveCode(language: string, code: string): void {
  localStorage.setItem(keyFor(language), code);
}
