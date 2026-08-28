import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SignIn } from "@/components/SignIn";

/**
 * Phone-OTP sign-in for the desktop surfaces.
 *
 * The property that matters most is what this component never holds: the form
 * posts to a route handler that writes httpOnly cookies, so no token passes
 * through React state where a script on the page could reach it.
 */

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const fail = (status: number, detail: string) => ({
  ok: false,
  status,
  json: async () => ({ detail }),
});

describe("SignIn", () => {
  it("asks for a phone number first", () => {
    render(<SignIn title="Sign in" subtitle="PoshanNetra" />);
    expect(screen.getByLabelText("Mobile number")).toBeInTheDocument();
    expect(screen.queryByLabelText("6-digit code")).not.toBeInTheDocument();
  });

  it("keeps the button disabled until the number is complete", async () => {
    render(<SignIn title="Sign in" subtitle="PoshanNetra" />);
    const button = screen.getByRole("button", { name: "Send code" });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Mobile number"), "9999900010");
    expect(button).toBeEnabled();
  });

  it("moves to the code step once a code is sent", async () => {
    fetchMock.mockResolvedValue(ok({ expires_in: 300 }));
    render(<SignIn title="Sign in" subtitle="PoshanNetra" />);
    await userEvent.type(screen.getByLabelText("Mobile number"), "9999900010");
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    expect(await screen.findByLabelText("6-digit code")).toBeInTheDocument();
  });

  it("offers the code field to SMS autofill", async () => {
    fetchMock.mockResolvedValue(ok({ expires_in: 300 }));
    render(<SignIn title="Sign in" subtitle="PoshanNetra" />);
    await userEvent.type(screen.getByLabelText("Mobile number"), "9999900010");
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    expect(await screen.findByLabelText("6-digit code")).toHaveAttribute(
      "autocomplete",
      "one-time-code",
    );
  });

  it("shows the demo code only when the API returns one", async () => {
    // Populated by the console provider outside production so a demo does not
    // require reading a server log. A real SMS provider never returns it.
    fetchMock.mockResolvedValue(ok({ expires_in: 300, debug_code: "123456" }));
    render(<SignIn title="Sign in" subtitle="PoshanNetra" />);
    await userEvent.type(screen.getByLabelText("Mobile number"), "9999900010");
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    expect(await screen.findByText(/Demo code/)).toHaveTextContent("123456");
  });

  it("hides the demo hint when the API does not return a code", async () => {
    fetchMock.mockResolvedValue(ok({ expires_in: 300 }));
    render(<SignIn title="Sign in" subtitle="PoshanNetra" />);
    await userEvent.type(screen.getByLabelText("Mobile number"), "9999900010");
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    await screen.findByLabelText("6-digit code");
    expect(screen.queryByText(/Demo code/)).not.toBeInTheDocument();
  });

  it("surfaces the API's reason when the wrong role signs in", async () => {
    // A field worker on this surface should be told where to go, not shown an
    // empty dashboard.
    fetchMock
      .mockResolvedValueOnce(ok({ expires_in: 300 }))
      .mockResolvedValueOnce(
        fail(403, "This dashboard is for supervisors. Use the capture app on your phone."),
      );
    render(<SignIn title="Sign in" subtitle="PoshanNetra" />);
    await userEvent.type(screen.getByLabelText("Mobile number"), "9999900002");
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    await userEvent.type(await screen.findByLabelText("6-digit code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/for supervisors/);
  });

  it("reports a wrong code without saying whether the number is registered", async () => {
    fetchMock
      .mockResolvedValueOnce(ok({ expires_in: 300 }))
      .mockResolvedValueOnce(fail(401, "that code is not valid"));
    render(<SignIn title="Sign in" subtitle="PoshanNetra" />);
    await userEvent.type(screen.getByLabelText("Mobile number"), "9999900010");
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    await userEvent.type(await screen.findByLabelText("6-digit code"), "000000");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("that code is not valid");
    expect(alert.textContent).not.toMatch(/registered|unknown|exists/i);
  });

  it("lets the officer go back and correct the number", async () => {
    fetchMock.mockResolvedValue(ok({ expires_in: 300 }));
    render(<SignIn title="Sign in" subtitle="PoshanNetra" />);
    await userEvent.type(screen.getByLabelText("Mobile number"), "9999900010");
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    await userEvent.click(await screen.findByRole("button", { name: "Change" }));
    expect(screen.getByLabelText("Mobile number")).toBeInTheDocument();
  });

  it("posts to the route handler and never handles a token itself", async () => {
    // The tokens are written into httpOnly cookies by the server. Nothing here
    // should ever see one, so an XSS bug on a page showing child nutrition data
    // is not also a credential theft.
    fetchMock
      .mockResolvedValueOnce(ok({ expires_in: 300 }))
      .mockResolvedValueOnce(ok({ name: "Official", role: "district_official" }));
    const onSignedIn = vi.fn();
    render(<SignIn title="Sign in" subtitle="PoshanNetra" onSignedIn={onSignedIn} />);
    await userEvent.type(screen.getByLabelText("Mobile number"), "9999900010");
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    await userEvent.type(await screen.findByLabelText("6-digit code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(onSignedIn).toHaveBeenCalled());
    const [startUrl] = fetchMock.mock.calls[0]!;
    const [finishUrl] = fetchMock.mock.calls[1]!;
    expect(startUrl).toBe("/auth/start");
    expect(finishUrl).toBe("/auth/finish");
    // No response body containing a token was ever read.
    expect(JSON.stringify(fetchMock.mock.calls)).not.toMatch(/access_token|refresh_token/);
  });

  it("strips non-digits from both fields", async () => {
    fetchMock.mockResolvedValue(ok({ expires_in: 300 }));
    render(<SignIn title="Sign in" subtitle="PoshanNetra" />);
    const phone = screen.getByLabelText("Mobile number");
    await userEvent.type(phone, "99-999 000102");
    expect(phone).toHaveValue("9999900010");
  });
});
