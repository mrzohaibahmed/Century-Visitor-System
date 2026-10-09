"use client";

import { Briefcase } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Card } from "@/components/ui/Card";
import { PersonalMaterialForm } from "@/components/visits/PersonalMaterialForm";
import { errorMessage } from "@/lib/api/client";
import { getVisit, updateVisitBelongings, type Visit } from "@/lib/api/visits";
import {
  belongingsList, emptyPersonalMaterial, filledBelongings, personalMaterialFromVisit, type PersonalMaterial,
  storedPersonalMaterial,
} from "@/lib/belongings";

/** Belongings for the visitor's current visit: opens the Personal Material Returnable slip. */
export function VisitorBelongings({ visitId }: { visitId: string }) {
  const [visit, setVisit] = useState<Visit | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [savingError, setSavingError] = useState<string | undefined>();
  const [draft, setDraft] = useState<PersonalMaterial>(emptyPersonalMaterial());
  const [vehicle, setVehicle] = useState("");

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const v = await getVisit(visitId);
      setVisit(v);
      setDraft(personalMaterialFromVisit(v.belongings, v.host.name ?? "", v.personal_material));
      setVehicle(v.vehicle_registration ?? "");
    } catch (e) {
      setLoadError(errorMessage(e));
    }
  }, [visitId]);

  useEffect(() => {
    // Initial load: state is updated by the asynchronous request completion.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const items = filledBelongings(draft);
  const hostName = visit?.host.name ?? "";

  async function onSave(next: { personalMaterial: PersonalMaterial; vehicle: string }) {
    setSavingError(undefined);
    try {
      const updated = await updateVisitBelongings(visitId, {
        belongings: belongingsList(next.personalMaterial),
        personal_material: storedPersonalMaterial(next.personalMaterial),
        vehicle_registration: next.vehicle.trim() || null,
      });
      setVisit(updated);
      setDraft(personalMaterialFromVisit(
        updated.belongings, updated.host.name ?? "", updated.personal_material,
      ));
      setVehicle(updated.vehicle_registration ?? "");
      setOpen(false);
      toast.success("Belongings updated.");
    } catch (e) {
      setSavingError(errorMessage(e));
    }
  }

  return (
    <>
      <Card title="Belongings" description="Personal material on the current visit." divided={false}>
        {loadError ? (
          <p role="alert" className="text-sm text-danger">{loadError}</p>
        ) : !visit ? (
          <p className="text-sm text-ink-muted">Loading belongings…</p>
        ) : (
          <div>
            <button
              type="button"
              onClick={() => { setSavingError(undefined); setOpen(true); }}
              aria-haspopup="dialog"
              aria-expanded={open}
              className="flex w-full min-h-14 items-center gap-3 rounded-xl border border-border-strong bg-surface px-3.5
                text-left transition-colors hover:border-ink-muted/50 focus-visible:border-brand-600
                focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-brand-600"
            >
              <Briefcase aria-hidden="true" className="size-5 shrink-0 text-ink-muted" />
              <span className="min-w-0 flex-1">
                {items.length === 0 ? (
                  <span className="text-lg text-ink-muted/70">Add personal material…</span>
                ) : (
                  <span className="caps block truncate text-lg text-ink">
                    {items.map((b) => b.description.trim()).join(", ")}
                  </span>
                )}
              </span>
              <span className="shrink-0 text-sm font-semibold text-brand-700">
                {items.length === 0 ? "Open form" : "Edit"}
              </span>
            </button>
            <p className="mt-1.5 text-sm text-ink-muted">Opens the personal material returnable slip.</p>
          </div>
        )}
      </Card>

      <PersonalMaterialForm
        open={open}
        value={draft}
        vehicle={vehicle}
        defaultContact={hostName}
        visitorName={visit?.visitor.name ?? undefined}
        visitNumber={visit?.visit_number}
        error={savingError}
        onClose={() => setOpen(false)}
        onSave={(next) => { void onSave(next); }}
      />
    </>
  );
}
