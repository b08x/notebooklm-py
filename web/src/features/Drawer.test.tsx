import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Drawer } from "./Drawer";

describe("Drawer (facts 17-18)", () => {
  it("renders when open and hides when closed", () => {
    const { rerender } = render(
      <Drawer open={false} onOpenChange={() => {}} title="Test Drawer">
        <div>Drawer content</div>
      </Drawer>,
    );
    expect(screen.queryByText("Drawer content")).not.toBeInTheDocument();

    rerender(
      <Drawer open={true} onOpenChange={() => {}} title="Test Drawer">
        <div>Drawer content</div>
      </Drawer>,
    );
    expect(screen.getByText("Drawer content")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("calls onOpenChange(false) when Escape is pressed", () => {
    const onOpenChange = vi.fn();
    render(
      <Drawer open={true} onOpenChange={onOpenChange} title="Test Drawer">
        <div>Drawer content</div>
      </Drawer>,
    );

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("calls onOpenChange(false) when close button is clicked", () => {
    const onOpenChange = vi.fn();
    render(
      <Drawer open={true} onOpenChange={onOpenChange} title="Test Drawer">
        <div>Drawer content</div>
      </Drawer>,
    );

    const closeBtn = screen.getByRole("button", { name: "Close" });
    fireEvent.click(closeBtn);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("supports left and right sides with custom width", () => {
    const { rerender } = render(
      <Drawer open={true} onOpenChange={() => {}} side="left" width={320} title="Left Drawer">
        <div>Left content</div>
      </Drawer>,
    );
    let dialog = screen.getByRole("dialog");
    expect(dialog).toHaveStyle({ width: "min(320px, calc(100vw - 16px))" });

    rerender(
      <Drawer open={true} onOpenChange={() => {}} side="right" width={400} title="Right Drawer">
        <div>Right content</div>
      </Drawer>,
    );
    dialog = screen.getByRole("dialog");
    expect(dialog).toHaveStyle({ width: "min(400px, calc(100vw - 16px))" });
  });
});
