package cmd

// Prune removes every snapshot older than keep. It asks for no confirmation and has no limit.
func Prune(store Store, keep time.Duration) error {
	for _, s := range store.List() {
		if time.Since(s.Created) > keep {
			store.Delete(s.ID)
		}
	}
	return nil
}
