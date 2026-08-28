import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Capture } from "../src/screens/Capture";
import { Growth } from "../src/screens/Growth";
import { Queue } from "../src/screens/Queue";
import { Settings } from "../src/screens/Settings";
import { SignIn } from "../src/screens/SignIn";
import { I18nProvider } from "../src/i18n/I18nProvider";
import { ThemeProvider } from "../src/theme/ThemeProvider";
import { cacheBeneficiaries, listQueue } from "../src/db/queue";
import type { QueuedCapture } from "../src/db/schema";
import * as api from "../src/api/client";

/**
 * Compression is unit-tested in tests/compress.test.ts against its own failure
 * modes. Here it is stubbed so these tests stay about the screen: jsdom never
 * decodes an image, so the real implementation would sit on its decode timeout
 * and turn every capture assertion into an eight-second wait.
 */
vi.mock("../src/capture/compress", async () => {
  const actual = await vi.importActual<typeof import("../src/capture/compress")>(
    "../src/capture/compress",
  );
  return {
    ...actual,
    compressPhoto: vi.fn(async (file: Blob) => ({
      blob: file,
      width: 1280,
      height: 960,
      bytes: file.size,
      originalBytes: file.size,
      passthrough: false,
    })),
  };
});

/**
 * Screen behaviour, with an emphasis on the accessibility properties Section
 * 9.1 makes non-negotiable: visible labels, touch targets a worker can hit,
 * status conveyed by more than colour, and errors that say what to do.
 */

/**
 * Select a child, waiting for the cached list to load first.
 *
 * The picker is populated from IndexedDB in an effect, so the <select> exists
 * with only its placeholder for a tick. Selecting before the options arrive is
 * a race that fails intermittently -- the kind of flake that gets a test
 * deleted rather than fixed.
 */
async function chooseChild(value: string) {
  const select = await screen.findByLabelText("बच्चा चुनें");
  // Wait for the real options, not just the placeholder. Selecting before the
  // cached list arrives is a race that fails intermittently -- the kind of
  // flake that gets a test deleted rather than fixed.
  await waitFor(() =>
    expect(within(select as HTMLSelectElement).getAllByRole("option").length).toBeGreaterThan(1),
  );
  await userEvent.selectOptions(select, value);
}

function renderScreen(ui: React.ReactElement) {
  return render(
    <ThemeProvider>
      <I18nProvider>{ui}</I18nProvider>
    </ThemeProvider>,
  );
}

/**
 * Enough children to cross the picker's search threshold, because a real
 * centre has forty-odd and the search control only renders above it. A
 * two-child fixture would test a screen no worker ever sees.
 */
const CHILDREN = [
  { id: "c1", name: "कमला डामोर", awcCode: "A1", dob: "2023-01-01", gender: "F", ageMonths: 38, poshanTrackerId: "PT1" },
  { id: "c2", name: "रमेश मीणा", awcCode: "A1", dob: "2022-06-01", gender: "M", ageMonths: 45, poshanTrackerId: "PT2" },
  ...Array.from({ length: 14 }, (_, i) => ({
    id: `f${i}`,
    name: `बालक ${i}`,
    awcCode: "A1",
    dob: "2022-01-01",
    gender: i % 2 ? "M" : "F",
    ageMonths: 30 + i,
    poshanTrackerId: `PTF${i}`,
  })),
];

beforeEach(async () => {
  await cacheBeneficiaries(CHILDREN);
  api.setSession("token", "refresh-token", {
    workerId: "w1", name: "सुनीता", role: "field_worker", awcCode: "A1", district: "Banswara",
  });
  window.matchMedia = vi.fn().mockImplementation((q: string) => ({
    matches: false, media: q, onchange: null,
    addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
  }));
});

describe("Capture screen", () => {
  it("renders in Hindi by default", async () => {
    renderScreen(<Capture />);
    expect(await screen.findByText("थाली की फ़ोटो")).toBeInTheDocument();
  });

  it("gives every control a visible label, not a placeholder", async () => {
    // A placeholder vanishes the moment typing starts -- exactly when a
    // hesitant user needs it most.
    renderScreen(<Capture />);
    expect(await screen.findByLabelText("बच्चा चुनें")).toBeInTheDocument();
    expect(screen.getByLabelText("भोजन")).toBeInTheDocument();
  });

  it("lists the cached children so selection works offline", async () => {
    renderScreen(<Capture />);
    const select = await screen.findByLabelText("बच्चा चुनें");
    // Matched against the option's full text rather than getByText: the label
    // is assembled from several JSX expressions, so it spans multiple text
    // nodes and a text matcher never sees it whole.
    await waitFor(() => {
      const labels = within(select as HTMLSelectElement)
        .getAllByRole("option")
        .map((o) => o.textContent ?? "");
      expect(labels.some((l) => l.includes("कमला डामोर"))).toBe(true);
      expect(labels.some((l) => l.includes("रमेश मीणा"))).toBe(true);
    });
  });

  it("refuses to start the camera before a child is chosen", async () => {
    // Otherwise a photograph exists with nobody to attribute it to.
    renderScreen(<Capture />);
    await userEvent.click(await screen.findByRole("button", { name: /फ़ोटो खींचें/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("पहले बच्चा चुनें");
  });

  it("warns that only the plate may be photographed", async () => {
    // Section 12 is absolute about this, so it is on the screen rather than
    // only in a training document.
    renderScreen(<Capture />);
    expect(await screen.findByText(/बच्चे की फ़ोटो कभी न लें/)).toBeInTheDocument();
  });

  it("always mounts the file input so the fallback cannot be unreachable", async () => {
    // The fallback runs on the oldest phones in the pilot. Mounting it
    // unconditionally means no viewfinder state can strand a worker.
    renderScreen(<Capture />);
    const input = await screen.findByTestId("file-input");
    expect(input).toHaveAttribute("accept", "image/*");
    expect(input).toHaveAttribute("capture", "environment");
  });

  it("saves a photo chosen through the fallback, offline", async () => {
    renderScreen(<Capture />);
    await chooseChild("c1");

    const input = screen.getByTestId("file-input") as HTMLInputElement;
    const file = new File([new Uint8Array(2048)], "plate.jpg", { type: "image/jpeg" });
    await userEvent.upload(input, file);

    await userEvent.click(await screen.findByRole("button", { name: /यह फ़ोटो ठीक है/ }));

    // Queued locally with no network involved at any point.
    await waitFor(async () => {
      const items = (await listQueue()) as QueuedCapture[];
      expect(items).toHaveLength(1);
      expect(items[0]?.beneficiaryId).toBe("c1");
      expect(items[0]?.status).toBe("pending");
      expect(items[0]?.awcCode).toBe("A1");
    });
  });

  it("tells the worker their photo is safe and will send itself", async () => {
    renderScreen(<Capture />);
    await chooseChild("c1");
    await userEvent.upload(
      screen.getByTestId("file-input"),
      new File([new Uint8Array(1024)], "p.jpg", { type: "image/jpeg" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: /यह फ़ोटो ठीक है/ }));
    expect(await screen.findByText(/अपने आप भेज दी जाएगी/)).toBeInTheDocument();
  });
});

describe("Growth screen", () => {
  it("uses a decimal keypad for measurements", async () => {
    // A height is 88.5, and Android's numeric pad has no decimal point.
    renderScreen(<Growth />);
    expect(await screen.findByLabelText(/लंबाई/)).toHaveAttribute("inputmode", "decimal");
    expect(screen.getByLabelText(/वज़न/)).toHaveAttribute("inputmode", "decimal");
  });

  it("shows a worked example rather than only a unit", async () => {
    renderScreen(<Growth />);
    expect(await screen.findByText("जैसे 88.5")).toBeInTheDocument();
  });

  it("rejects a non-numeric measurement with a recoverable message", async () => {
    renderScreen(<Growth />);
    await chooseChild("c1");
    await userEvent.type(screen.getByLabelText(/लंबाई/), "abc");
    await userEvent.type(screen.getByLabelText(/वज़न/), "11");
    await userEvent.click(screen.getByRole("button", { name: /दर्ज करें/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("सही संख्या भरें");
  });

  it("queues the measurement before attempting to send it", async () => {
    // If the request fails the numbers are already durable; the worker does
    // not have to remember and re-enter them.
    vi.spyOn(api, "recordGrowth").mockRejectedValue(new api.ApiError("offline", 0));
    renderScreen(<Growth />);
    await chooseChild("c1");
    await userEvent.type(screen.getByLabelText(/लंबाई/), "88.5");
    await userEvent.type(screen.getByLabelText(/वज़न/), "11.2");
    await userEvent.click(screen.getByRole("button", { name: /दर्ज करें/ }));

    await waitFor(async () => {
      const items = await listQueue();
      expect(items).toHaveLength(1);
      expect(items[0]).toMatchObject({ kind: "growth", heightCm: 88.5, weightKg: 11.2 });
    });
  });

  it("tells the worker to refer a severely malnourished child", async () => {
    // SAM is a referral today, not a statistic. The screen says what to do.
    vi.spyOn(api, "recordGrowth").mockResolvedValue({
      entry: {
        id: "g1", classification: "SAM", standard_used: "who_2006_0_60m",
        waz_score: -3.4, haz_score: -2.1, whz_score: -3.6, baz_score: null,
        data_quality_flags: [],
      },
      notes: [],
    });
    renderScreen(<Growth />);
    await chooseChild("c1");
    await userEvent.type(screen.getByLabelText(/लंबाई/), "88");
    await userEvent.type(screen.getByLabelText(/वज़न/), "8");
    await userEvent.click(screen.getByRole("button", { name: /दर्ज करें/ }));

    expect(await screen.findByText(/गंभीर कुपोषण/)).toBeInTheDocument();
    expect(screen.getByText(/तुरंत पर्यवेक्षक को दिखाएँ/)).toBeInTheDocument();
  });

  it("surfaces an implausible reading as 'measure again'", async () => {
    // The server flags these using WHO Anthro bounds. Far more useful to the
    // worker than a status computed from a typo.
    vi.spyOn(api, "recordGrowth").mockResolvedValue({
      entry: {
        id: "g2", classification: "normal", standard_used: "who_2006_0_60m",
        waz_score: 1, haz_score: 9.3, whz_score: 0, baz_score: null,
        data_quality_flags: ["haz"],
      },
      notes: [],
    });
    renderScreen(<Growth />);
    await chooseChild("c1");
    await userEvent.type(screen.getByLabelText(/लंबाई/), "188");
    await userEvent.type(screen.getByLabelText(/वज़न/), "11");
    await userEvent.click(screen.getByRole("button", { name: /दर्ज करें/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/दोबारा मापें/);
  });
});

describe("Queue screen", () => {
  it("says plainly when there is nothing waiting", async () => {
    renderScreen(<Queue />);
    expect(await screen.findByText("भेजने के लिए कुछ नहीं है")).toBeInTheDocument();
  });

  it("offers a manual send, because background sync is not dependable", async () => {
    // Section 7 asks for this explicitly.
    renderScreen(<Queue />);
    expect(await screen.findByRole("button", { name: /अभी भेजें/ })).toBeInTheDocument();
  });

  it("disables the send button when the queue is empty", async () => {
    renderScreen(<Queue />);
    expect(await screen.findByRole("button", { name: /अभी भेजें/ })).toBeDisabled();
  });
});

describe("Settings screen", () => {
  it("presents language and theme as radio groups, not hidden menus", async () => {
    // Every option visible without an interaction, each a full-width target.
    renderScreen(<Settings onSignedOut={() => {}} />);
    const groups = await screen.findAllByRole("radiogroup");
    expect(groups).toHaveLength(2);
  });

  it("offers all four appearance modes including sunlight", async () => {
    renderScreen(<Settings onSignedOut={() => {}} />);
    for (const label of ["दिन", "रात", "फ़ोन जैसा", "तेज़ धूप"]) {
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
  });

  it("explains what the sunlight mode is for", async () => {
    renderScreen(<Settings onSignedOut={() => {}} />);
    expect(await screen.findByText(/बाहर धूप में पढ़ने के लिए/)).toBeInTheDocument();
  });

  it("switches the whole interface to English", async () => {
    renderScreen(<Settings onSignedOut={() => {}} />);
    await userEvent.click(await screen.findByText("English"));
    expect(await screen.findByText("Settings")).toBeInTheDocument();
  });

  it("confirms before signing out, since it clears unsent work", async () => {
    renderScreen(<Settings onSignedOut={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: /साइन आउट/ }));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
  });
});


describe("SignIn screen", () => {
  it("caps the phone number at ten digits", async () => {
    // Found by driving the real UI: `maxLength` alone let an eleven-digit
    // value through, which enabled the button and then failed server-side
    // with a message that did not explain why.
    renderScreen(<SignIn onSignedIn={() => {}} />);
    const input = await screen.findByLabelText("मोबाइल नंबर");
    await userEvent.type(input, "99999000011234");
    expect(input).toHaveValue("9999900001");
  });

  it("strips anything that is not a digit", async () => {
    renderScreen(<SignIn onSignedIn={() => {}} />);
    const input = await screen.findByLabelText("मोबाइल नंबर");
    await userEvent.type(input, "99-999 00001");
    expect(input).toHaveValue("9999900001");
  });

  it("keeps the button disabled until the number is complete", async () => {
    renderScreen(<SignIn onSignedIn={() => {}} />);
    const button = screen.getByRole("button", { name: "कोड भेजें" });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText("मोबाइल नंबर"), "999990000");
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText("मोबाइल नंबर"), "1");
    expect(button).toBeEnabled();
  });

  it("uses a numeric keypad", async () => {
    renderScreen(<SignIn onSignedIn={() => {}} />);
    expect(await screen.findByLabelText("मोबाइल नंबर")).toHaveAttribute("inputmode", "numeric");
  });

  it("explains that sign-in is the one step needing internet", async () => {
    renderScreen(<SignIn onSignedIn={() => {}} />);
    expect(
      await screen.findByText("वही नंबर जो आंगनवाड़ी में दर्ज है"),
    ).toBeInTheDocument();
  });

  it("moves to the code step after requesting one", async () => {
    vi.spyOn(api, "requestOtp").mockResolvedValue({
      expiresIn: 300, messageHi: "…", messageEn: "…",
    });
    renderScreen(<SignIn onSignedIn={() => {}} />);
    await userEvent.type(screen.getByLabelText("मोबाइल नंबर"), "9999900001");
    await userEvent.click(screen.getByRole("button", { name: "कोड भेजें" }));
    expect(await screen.findByLabelText("6 अंकों का कोड")).toBeInTheDocument();
  });

  it("offers the code field to the phone's SMS autofill", async () => {
    // autocomplete="one-time-code" is what lets Android surface the code from
    // the notification instead of the worker retyping it.
    vi.spyOn(api, "requestOtp").mockResolvedValue({
      expiresIn: 300, messageHi: "…", messageEn: "…",
    });
    renderScreen(<SignIn onSignedIn={() => {}} />);
    await userEvent.type(screen.getByLabelText("मोबाइल नंबर"), "9999900001");
    await userEvent.click(screen.getByRole("button", { name: "कोड भेजें" }));
    expect(await screen.findByLabelText("6 अंकों का कोड")).toHaveAttribute(
      "autocomplete",
      "one-time-code",
    );
  });

  it("says a code is wrong without blaming the number", async () => {
    vi.spyOn(api, "requestOtp").mockResolvedValue({
      expiresIn: 300, messageHi: "…", messageEn: "…",
    });
    vi.spyOn(api, "verifyOtp").mockRejectedValue(new api.ApiError("nope", 401));
    renderScreen(<SignIn onSignedIn={() => {}} />);
    await userEvent.type(screen.getByLabelText("मोबाइल नंबर"), "9999900001");
    await userEvent.click(screen.getByRole("button", { name: "कोड भेजें" }));
    await userEvent.type(await screen.findByLabelText("6 अंकों का कोड"), "000000");
    await userEvent.click(screen.getByRole("button", { name: "साइन इन करें" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("यह कोड सही नहीं है");
  });

  it("explains a throttle rather than showing a generic error", async () => {
    vi.spyOn(api, "requestOtp").mockRejectedValue(new api.ApiError("slow down", 429));
    renderScreen(<SignIn onSignedIn={() => {}} />);
    await userEvent.type(screen.getByLabelText("मोबाइल नंबर"), "9999900001");
    await userEvent.click(screen.getByRole("button", { name: "कोड भेजें" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/बहुत बार कोशिश हुई/);
  });
});


describe("child picker labelling", () => {
  it("labels the search field and the select separately", async () => {
    // Found by looking at the rendered screen: with only the select labelled,
    // the "select child" label sat directly above the search box and read as
    // its label, leaving the control a worker actually needs unlabelled.
    renderScreen(<Capture />);
    const search = await screen.findByLabelText("नाम खोजें");
    const select = screen.getByLabelText("बच्चा चुनें");
    expect(search.tagName).toBe("INPUT");
    expect(select.tagName).toBe("SELECT");
    expect(search).not.toBe(select);
  });

  it("narrows the list without touching the network", async () => {
    renderScreen(<Capture />);
    const select = (await screen.findByLabelText("बच्चा चुनें")) as HTMLSelectElement;
    await waitFor(() =>
      expect(within(select).getAllByRole("option").length).toBeGreaterThan(1),
    );
    await userEvent.type(screen.getByLabelText("नाम खोजें"), "रमेश");
    await waitFor(() => {
      const labels = within(select).getAllByRole("option").map((o) => o.textContent ?? "");
      expect(labels.some((l) => l.includes("रमेश"))).toBe(true);
      expect(labels.some((l) => l.includes("कमला"))).toBe(false);
    });
  });
});
