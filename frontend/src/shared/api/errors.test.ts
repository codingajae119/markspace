import { describe, it, expect } from "vitest";

import { ApiError, parseErrorResponse } from "@/shared/api/errors";
import type { ErrorResponse } from "@/shared/api/errors";

describe("parseErrorResponse", () => {
  it("maps a well-formed ErrorResponse to an ApiError preserving status/code/message", () => {
    const body: ErrorResponse = { code: "not_found", message: "Document not found" };

    const err = parseErrorResponse(404, body);

    expect(err).toBeInstanceOf(ApiError);
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("ApiError");
    expect(err.status).toBe(404);
    expect(err.code).toBe("not_found");
    expect(err.message).toBe("Document not found");
    expect(err.fieldErrors).toEqual([]);
    // raw is the normalized ErrorResponse (field_errors filled to []).
    expect(err.raw).toEqual({ ...body, field_errors: [] });
  });

  it("preserves the field_errors array for a validation_error body", () => {
    const body: ErrorResponse = {
      code: "validation_error",
      message: "Request validation failed",
      field_errors: [
        { field: "name", message: "must not be empty" },
        { field: "email", message: "invalid format" },
      ],
    };

    const err = parseErrorResponse(422, body);

    expect(err.status).toBe(422);
    expect(err.code).toBe("validation_error");
    expect(err.fieldErrors).toEqual([
      { field: "name", message: "must not be empty" },
      { field: "email", message: "invalid format" },
    ]);
  });

  it("normalizes field_errors null/absent to an empty array", () => {
    const withNull = parseErrorResponse(409, {
      code: "conflict",
      message: "state conflict",
      field_errors: null,
    });
    expect(withNull.fieldErrors).toEqual([]);

    const withAbsent = parseErrorResponse(403, {
      code: "forbidden",
      message: "not allowed",
    });
    expect(withAbsent.fieldErrors).toEqual([]);
  });

  it("normalizes a non-object body to the internal default without leaking details", () => {
    const err = parseErrorResponse(500, "boom: NullPointerException at line 42");

    expect(err.code).toBe("internal");
    expect(err.message).not.toContain("NullPointerException");
    expect(err.message.length).toBeGreaterThan(0);
    expect(err.fieldErrors).toEqual([]);
    expect(err.status).toBe(500);
    expect(err.raw).toBeUndefined();
  });

  it("normalizes a null body to the internal default", () => {
    const err = parseErrorResponse(502, null);

    expect(err.code).toBe("internal");
    expect(err.fieldErrors).toEqual([]);
    expect(err.raw).toBeUndefined();
  });

  it("normalizes a body missing message to the internal default", () => {
    const err = parseErrorResponse(400, { code: "not_found" });

    expect(err.code).toBe("internal");
    expect(err.fieldErrors).toEqual([]);
  });

  it("normalizes a body missing code to the internal default", () => {
    const err = parseErrorResponse(400, { message: "something happened" });

    expect(err.code).toBe("internal");
    expect(err.fieldErrors).toEqual([]);
  });

  it("normalizes a body with non-string code/message to the internal default", () => {
    const err = parseErrorResponse(400, { code: 42, message: { nested: true } });

    expect(err.code).toBe("internal");
    expect(err.fieldErrors).toEqual([]);
  });

  it("drops malformed field_errors entries while keeping a valid ErrorResponse", () => {
    const err = parseErrorResponse(422, {
      code: "validation_error",
      message: "Request validation failed",
      field_errors: [
        { field: "name", message: "required" },
        { field: 1, message: "bad" },
        "not-an-object",
      ],
    });

    expect(err.code).toBe("validation_error");
    expect(err.fieldErrors).toEqual([{ field: "name", message: "required" }]);
  });

  it("accepts an unknown-but-string code (forward-compatible with backend catalog)", () => {
    const err = parseErrorResponse(418, { code: "teapot", message: "I am a teapot" });

    expect(err.code).toBe("teapot");
    expect(err.message).toBe("I am a teapot");
  });
});
