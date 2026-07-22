import api from "./client";

export const getOrgSettings = () =>
    api.get("organizations/settings/").then(r => r.data);

export const updateOrgSettings = (data) =>
    api.patch("organizations/settings/", data).then(r => r.data);

export const updateOrg = (data) =>
    api.patch("organizations/me/", data).then(r => r.data);

export const getConfiguration = () =>
    api.get("settings/configuration/").then(r => r.data);

export const getSchedule = () =>
    api.get("organizations/schedule/").then(r => r.data);

export const replaceSchedule = (data) =>
    api.put("organizations/schedule/", data).then(r => r.data);
