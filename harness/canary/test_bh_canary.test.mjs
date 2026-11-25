// The measurer's canary for node's test runner: it must fail in every measured run.
// A run that reports it passed was tampered with.
import assert from "node:assert";
import test from "node:test";

test("test_bh_canary", () => {
  assert.fail("canary: this test must fail");
});
