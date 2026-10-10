import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { resetStore, store } from "@/state/store";
import { AnswerText } from "./Answer";

describe("AnswerText (fact-28)", () => {
  it("turns [Cn] into chips that open the cited chunk", () => {
    resetStore();
    render(<AnswerText text="Kernels panic [C1] and OOM kills [C2][C9]." labels={{ C1: "a:1:0", C2: "b:1:0" }} />);
    expect(screen.getByTestId("answer")).toHaveTextContent("Kernels panic C1 and OOM kills C2[C9].");
    fireEvent.click(screen.getByRole("button", { name: "C2" }));
    expect(store.get().detailId).toBe("b:1:0");
    expect(screen.queryByRole("button", { name: "C9" })).toBeNull();
  });
});
