// Mirrors backend/app/schemas/* for type-safe API I/O on the client.

export type Holiday = {
  id: number;
  country: string;
  day: string;
  name_zh: string;
  name_en: string;
  kind: string;
  is_workday: boolean;
  notes: string | null;
};

export type LeaveStrategy = {
  id: number;
  year: number;
  holiday_key: string;
  label_zh: string;
  pto_days: number;
  total_days: number;
  window_start: string;
  window_end: string;
  description: string | null;
};

export type TripType = "one_way" | "round_trip" | "multi_city";

export type CabinClass =
  | "economy"
  | "premium_economy"
  | "business"
  | "first";

export type TicketStrategyType =
  | "standard"
  | "open_jaw"
  | "reverse"
  | "back_to_back_4leg"
  | "hidden_city";

export type DateWindowRole = "outbound" | "return" | "segment";

export type RiskLevel = "low" | "medium" | "high";

export type DateWindowIn = {
  role: DateWindowRole;
  anchor_date: string; // ISO date
  flex_before: number;
  flex_after: number;
  allow_weekend_only?: boolean;
  sequence?: number;
  segment_origin?: string | null;
  segment_destination?: string | null;
};

export type CandidateWindowIn = {
  label?: string | null;
  holiday_key?: string | null;
  depart: string; // ISO date
  return_date?: string | null;
  depart_flex: number;
  return_flex: number;
};

export type ScoringWeights = {
  price: number;
  pto_efficiency: number;
  flight_time: number;
  strategy_risk: number;
};

export type ItineraryRequestIn = {
  trip_type: TripType;
  cabin: CabinClass;
  adults: number;
  children: number;
  infants: number;
  origins: string[];
  destinations: string[];
  strategies: TicketStrategyType[];
  holiday_key: string | null;
  candidate_windows?: CandidateWindowIn[];
  max_total_budget: number | null;
  max_pto_days: number | null;
  scoring_weights: ScoringWeights | null;
  date_windows: DateWindowIn[];
  back_to_back_outer_stations: string[];
  outer_stay_days: number;
};

export type FlightLegOut = {
  origin: string;
  destination: string;
  departure: string;
  arrival: string;
  carrier: string;
  flight_number: string;
  cabin: CabinClass;
  stops: number;
};

export type BookingLinkOut = {
  source: string;
  label: string;
  url: string;
};

export type TicketOfferOut = {
  offer_id: string;
  legs: FlightLegOut[];
  total_price: number;
  currency: string;
  fare_class: string | null;
  baggage_through_checked: boolean;
  issuer: string | null;
  booking_links?: BookingLinkOut[];
};

export type RiskWarningOut = {
  level: RiskLevel;
  code: string;
  message: string;
};

export type StrategyPlanOut = {
  strategy: TicketStrategyType;
  tickets: TicketOfferOut[];
  total_cost: number;
  currency: string;
  pto_days: number;
  total_travel_days: number;
  warnings: RiskWarningOut[];
  score: number | null;
  explain: string | null;
  window_label?: string | null;
  ticket_roles?: string[];
  trips?: string[];
};

export type ProviderCacheStats = {
  hits?: number;
  misses?: number;
  total?: number;
  unique_queries?: number;
};

export type SearchResult = {
  request_echo: Record<string, unknown>;
  date_matrix_size: number;
  plans: StrategyPlanOut[];
  provider_cache?: ProviderCacheStats;
  notices?: string[];
};

export type AirportOut = {
  code: string;
  name_zh: string;
  country: string;
  group: string;
};

export type AirportCatalog = {
  origins: AirportOut[];
  destinations: AirportOut[];
  outstations: AirportOut[];
};
