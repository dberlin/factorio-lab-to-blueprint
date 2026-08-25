// jest-dom ships type augmentation for jest ("jest.d.ts") and vitest
// ("vitest.d.ts") but not for rstest. rstest exposes an empty `Matchers<T>`
// interface from '@rstest/core' as its own augmentation point (mirroring
// vitest's `Assertion<T>` pattern) — wire jest-dom's matchers into it so
// `toHaveTextContent` etc. type-check on `expect(...)`.
import type { TestingLibraryMatchers } from '@testing-library/jest-dom/matchers';

declare module '@rstest/core' {
  interface Matchers<T = unknown> extends TestingLibraryMatchers<unknown, T> {}
}
