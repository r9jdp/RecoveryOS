import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "./Button";

describe("Button", () => {
  it("exposes a disabled busy state while loading", () => {
    render(<Button loading>Approve recovery</Button>);

    const button = screen.getByRole("button", { name: "Approve recovery" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });
});

