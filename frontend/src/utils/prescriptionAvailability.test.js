import { describe, expect, it } from "vitest";
import { authoritativePresentationMax } from "./prescriptionAvailability";

describe("authoritativePresentationMax", () => {
    it("uses the backend projection without recalculating from base units", () => {
        expect(authoritativePresentationMax({
            max_selectable_quantity: 2,
            conversion_factor: "100",
            remaining_quantity_base: "1",
        })).toBe(2);
    });

    it.each([undefined, null, -1, 1.5, "NaN"])(
        "fails closed for an invalid API maximum: %s",
        value => {
            expect(authoritativePresentationMax({
                max_selectable_quantity: value,
            })).toBe(0);
        },
    );
});
