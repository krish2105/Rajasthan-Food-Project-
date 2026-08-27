import { useMemo, useState } from "react";
import type { CachedBeneficiary } from "../db/schema";
import { useI18n } from "../i18n/I18nProvider";

/**
 * Beneficiary selector.
 *
 * A native <select> over the locally cached list, per Section 7: "dropdown from
 * cached list, not a live search". A search box that queried the server would
 * be empty exactly when the worker is standing in a kitchen with no signal.
 *
 * The text filter above it is a local narrowing of that same cached list, not a
 * query. It only appears once the list is long enough to be awkward to scroll,
 * because Section 9.1 asks for dropdowns and selectors over text fields -- an
 * unnecessary text input on a small screen is a keyboard covering half the UI.
 */

const SEARCH_THRESHOLD = 12;

export function ChildPicker({
  children,
  value,
  onChange,
  id = "child",
  required = true,
}: {
  children: CachedBeneficiary[];
  value: string;
  onChange: (id: string) => void;
  id?: string;
  required?: boolean;
}) {
  const { t } = useI18n();
  const [filter, setFilter] = useState("");

  const filtered = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return children;
    return children.filter((c) => c.name.toLowerCase().includes(needle));
  }, [children, filter]);

  return (
    <div className="field">
      {/* The narrowing field comes first because that is the order a worker
          uses it, but it carries its own visible label. Without one, the
          "select child" label sits directly above the search box and appears
          to belong to it -- so the control a worker actually needs to find is
          the only one on screen with no label next to it. */}
      {children.length > SEARCH_THRESHOLD && (
        <>
          <label className="field__label" htmlFor={`${id}-search`}>
            {t("searchChild")}
          </label>
          <input
            id={`${id}-search`}
            className="input"
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ marginBottom: "var(--space-4)" }}
          />
        </>
      )}

      <label className="field__label" htmlFor={id}>
        {t("selectChild")}
      </label>

      <select
        id={id}
        className="select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
      >
        <option value="">{t("selectChildPlaceholder")}</option>
        {filtered.map((child) => (
          <option key={child.id} value={child.id}>
            {child.name} — {Math.floor(child.ageMonths / 12)}
            {t("years")}
          </option>
        ))}
      </select>
    </div>
  );
}
