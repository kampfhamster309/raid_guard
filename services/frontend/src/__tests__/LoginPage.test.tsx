import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginPage } from "../components/LoginPage";
import * as api from "../api";

vi.mock("../api", () => ({
  login: vi.fn(),
  setToken: vi.fn(),
  getToken: vi.fn(() => null),
  clearToken: vi.fn(),
}));

describe("LoginPage", () => {
  it("renders username and password fields", () => {
    render(<LoginPage onLogin={vi.fn()} />);
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it("calls onLogin after successful login", async () => {
    const user = userEvent.setup();
    vi.mocked(api.login).mockResolvedValueOnce("tok123");
    const onLogin = vi.fn();
    render(<LoginPage onLogin={onLogin} />);

    await user.type(screen.getByLabelText(/username/i), "admin");
    await user.type(screen.getByLabelText(/password/i), "secret");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(onLogin).toHaveBeenCalledOnce());
    expect(api.setToken).toHaveBeenCalledWith("tok123");
  });

  it("shows error on failed login", async () => {
    const user = userEvent.setup();
    vi.mocked(api.login).mockRejectedValueOnce(new Error("Invalid credentials"));
    render(<LoginPage onLogin={vi.fn()} />);

    await user.type(screen.getByLabelText(/username/i), "admin");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Invalid credentials")
    );
  });
});
