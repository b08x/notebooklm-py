import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NewChunksPill } from "./NewChunksPill";

describe("NewChunksPill (fact-33)", () => {
  it("is hidden at zero and shows the count; clicking refreshes", () => {
    const onClick = vi.fn();
    const { rerender } = render(<NewChunksPill count={0} onClick={onClick} />);
    expect(screen.queryByRole("button")).toBeNull();
    rerender(<NewChunksPill count={37} onClick={onClick} />);
    fireEvent.click(screen.getByRole("button", { name: /37 new chunks/ }));
    expect(onClick).toHaveBeenCalledOnce();
    rerender(<NewChunksPill count={1} onClick={onClick} />);
    expect(screen.getByRole("button", { name: /1 new chunk$/ })).toBeInTheDocument();
  });
});
